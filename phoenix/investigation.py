from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import urlsplit

import httpx

from .domain import Conflict, digest, dump, now, uid


def public_headers(headers):
    return {k: ('<redacted>' if k.lower() in ('authorization', 'cookie', 'set-cookie', 'x-api-key') else v)
            for k, v in headers.items()}


class Investigation:
    """PHOENIX inventory/coverage/traffic concepts in the native run journal."""
    def __init__(self, components):
        self.c, self.store = components, components.store

    def setting(self, key, default=None):
        rows = self.store.all('SELECT value FROM integration_settings WHERE key=?', (key,))
        return json.loads(rows[0]['value']) if rows else default

    def configure(self, key, value):
        self.store.execute('INSERT INTO integration_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (key, dump(value)))

    def asset(self, rid, kind, value, source='operator', parent_id=None, metadata=None, tested=False):
        self.store.run(rid)
        if kind not in ('domain', 'ip', 'port', 'site', 'endpoint', 'subdomain', 'service', 'app'):
            raise ValueError('Unknown asset kind')
        if not value.strip() or len(value) > 6000:
            raise ValueError('Asset value must contain 1..6000 characters')
        if parent_id:
            self.store.one('SELECT id FROM assets WHERE id=? AND run_id=?', (parent_id, rid))
        aid = uid('asset')
        self.store.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?) '
            'ON CONFLICT(run_id,kind,value) DO UPDATE SET '
            "metadata=CASE WHEN excluded.metadata='{}' THEN assets.metadata ELSE excluded.metadata END, "
            'tested=MAX(assets.tested,excluded.tested),updated=excluded.updated',
            (aid, rid, kind, value.strip(), parent_id, source[:300], dump(metadata or {}), int(tested), now(), now()))
        return self.store.one('SELECT * FROM assets WHERE run_id=? AND kind=? AND value=?', (rid, kind, value.strip()))

    def inventory(self, rid):
        run = self.store.run(rid)
        for origin in self.store.challenge(run['challenge_id'])['targets']:
            p = urlsplit(origin)
            host = self.asset(rid, 'domain', p.hostname, 'challenge-scope')
            self.asset(rid, 'site' if p.scheme.startswith('http') else 'service', origin,
                       'challenge-scope', host['id'])
        rows = self.store.all('SELECT * FROM assets WHERE run_id=? ORDER BY created,id', (rid,))
        for row in rows:
            row['metadata'] = json.loads(row['metadata'])
        return {'items': rows, 'tested': sum(r['tested'] for r in rows), 'total': len(rows),
                'edges': [{'source': r['parent_id'], 'target': r['id']} for r in rows if r['parent_id']]}

    def intercept(self, rid):
        return bool(self.setting('intercept:'+rid, False))

    async def wait_for_approval(self, rid, tid, request):
        aid = uid('approval')
        # Secrets remain in process only. Never put browser cookies into approval events.
        safe = {**request, 'headers': public_headers(request.get('headers', {}))}
        self.store.execute('INSERT INTO request_approvals VALUES(?,?,?,?,?,?,?)',
                           (aid, rid, tid, dump(safe), 'pending', now(), now()))
        self.store.event(rid, 'request.approval_required', {'approval_id': aid, 'url': request['url'], 'method': request['method']}, tid)
        try:
            for _ in range(1200):
                row = self.store.one('SELECT * FROM request_approvals WHERE id=?', (aid,))
                if row['state'] == 'approved':
                    edited = json.loads(row['request'])
                    # Preserve only the in-memory secret fields; approved edits cannot
                    # expand scope or change authentication to an unrelated target.
                    edited['headers'] = {**request.get('headers', {}), **{
                        k: v for k, v in edited.get('headers', {}).items() if v != '<redacted>'}}
                    return edited
                if row['state'] != 'pending':
                    raise Conflict('Request was rejected or cancelled')
                await asyncio.sleep(0.25)
            raise Conflict('Request approval timed out')
        finally:
            self.store.execute("UPDATE request_approvals SET state='cancelled',updated=? WHERE id=? AND state='pending'", (now(), aid))

    def decide(self, rid, aid, approve, edit=None):
        row = self.store.one('SELECT * FROM request_approvals WHERE id=? AND run_id=?', (aid, rid))
        request = edit if edit is not None else json.loads(row['request'])
        self.c.tools.target(rid, request['url'], ('http', 'https'))
        if self.store.execute('UPDATE request_approvals SET state=?,request=?,updated=? WHERE id=? AND state=?',
                ('approved' if approve else 'rejected', dump(request), now(), aid, 'pending')) != 1:
            raise Conflict('This request already has a decision')
        self.store.event(rid, 'request.approval_decided', {'approval_id': aid, 'approved': approve})
        return {'id': aid, 'state': 'approved' if approve else 'rejected'}

    async def request(self, rid, tid, method, url, headers=None, body='', timeout=15, source='http_request', browser=False):
        self.c.tools.target(rid, url, ('http', 'https'))
        headers = dict(headers or {})
        if any(k.lower() in ('host', 'connection', 'proxy-authorization') for k in headers):
            raise ValueError('Host/proxy/connection header overrides are not accepted')
        payload = {'method': method, 'url': url, 'headers': headers, 'body': body}
        if self.intercept(rid):
            payload = await self.wait_for_approval(rid, tid, payload)
            self.c.tools.target(rid, payload['url'], ('http', 'https'))
            if any(k.lower() in ('host', 'connection', 'proxy-authorization') for k in payload['headers']):
                raise ValueError('Host/proxy/connection header overrides are not accepted')
        started = now()
        async with httpx.AsyncClient(transport=self.c.tools.transport, timeout=timeout, follow_redirects=False, trust_env=False) as client:
            async with client.stream(payload['method'], payload['url'], headers=payload['headers'], content=payload['body'].encode()) as response:
                data, truncated = bytearray(), False
                async for block in response.aiter_bytes():
                    room = 2*1024*1024-len(data)
                    data.extend(block[:room])
                    if len(block) > room:
                        truncated = True
                        break
                result = {'status': response.status_code, 'headers': public_headers(dict(response.headers)),
                          'body': data.decode('utf-8', 'replace'), 'body_base64': base64.b64encode(data).decode(),
                          'truncated': truncated, 'sha256': digest(data), 'duration_ms': round((now()-started)*1000)}
                transport_headers = dict(response.headers)
        traffic_id = uid('traffic')
        safe = {**payload, 'headers': public_headers(payload['headers']), 'source': source}
        self.store.execute('INSERT INTO traffic VALUES(?,?,?,?,?,?,?)',
                           (traffic_id, rid, tid, dump(safe), dump(result), None, now()))
        p = urlsplit(payload['url'])
        origin = self.c.tools.target(rid, payload['url'], ('http', 'https'))
        host = self.asset(rid, 'domain', p.hostname, source, tested=True)
        site = self.asset(rid, 'site', origin, source, host['id'], tested=True)
        self.asset(rid, 'endpoint', payload['url'], source, site['id'], {'method': method, 'status': result['status']}, True)
        self.store.event(rid, 'traffic.recorded', {'traffic_id': traffic_id, 'method': method, 'url': url, 'status': result['status']}, tid)
        result['traffic_id'] = traffic_id
        if browser:
            result['_transport_headers'] = transport_headers
        return result

    def traffic(self, rid):
        self.store.run(rid)
        rows = self.store.all('SELECT id,run_id,request,response,evidence_id,created FROM traffic WHERE run_id=? ORDER BY created DESC LIMIT 300', (rid,))
        for row in rows:
            row['request'], row['response'] = json.loads(row['request']), json.loads(row['response'])
            row['response'].pop('body_base64', None)
        return rows
