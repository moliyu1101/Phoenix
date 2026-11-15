from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx

from .domain import dump, now


class ScopeSentry:
    """PHOENIX ScopeSentry MCP calls and field mapping, adapted to native run assets."""
    TOOLS = {'list_projects_data', 'list_tasks', 'get_project', 'list_assets'}

    def __init__(self, components):
        self.c = components
        self.transport = None

    def configure(self, endpoint, key):
        parsed = urlsplit(endpoint)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('Specify a valid ScopeSentry MCP HTTP endpoint')
        previous = self.c.investigation.setting('scopesentry', {})
        ref = self.c.platforms.secrets.put('scopesentry', 'api-key', key) if key else previous.get('credential_ref')
        if not ref:
            raise ValueError('A ScopeSentry API key is required')
        self.c.investigation.configure('scopesentry', {'endpoint': endpoint, 'credential_ref': ref})
        return self.status()

    def status(self):
        value = self.c.investigation.setting('scopesentry', {})
        return {'endpoint': value.get('endpoint', ''), 'key_configured': bool(value.get('credential_ref'))}

    @staticmethod
    def decode(response):
        response.raise_for_status()
        text = response.text
        if 'text/event-stream' in response.headers.get('content-type', ''):
            candidates = [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith('data:')]
            value = next((v for v in reversed(candidates) if 'result' in v or 'error' in v), {})
        else:
            value = response.json() if text.strip() else {}
        if value.get('error'):
            raise ValueError('ScopeSentry MCP rejected the request')
        return value.get('result', value)

    async def call(self, name, arguments):
        if name not in self.TOOLS:
            raise ValueError('Unsupported ScopeSentry operation')
        config = self.c.investigation.setting('scopesentry')
        if not config:
            raise ValueError('Configure ScopeSentry first')
        headers = {'X-API-Key': self.c.platforms.secrets.resolve(config['credential_ref']),
                   'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-03-26'}
        async with httpx.AsyncClient(transport=self.transport, timeout=45, trust_env=False, follow_redirects=False) as client:
            response = await client.post(config['endpoint'], headers=headers, json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                    'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'Phoenix', 'version': '0.1.0'}}})
            self.decode(response)
            if response.headers.get('Mcp-Session-Id'):
                headers['Mcp-Session-Id'] = response.headers['Mcp-Session-Id']
            notification = await client.post(config['endpoint'], headers=headers,
                json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            notification.raise_for_status()
            response = await client.post(config['endpoint'], headers=headers,
                json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})
            result = self.decode(response)
            if result.get('isError'):
                raise ValueError('ScopeSentry tool failed')
            if result.get('structuredContent'):
                return result['structuredContent']
            for content in result.get('content', []):
                if content.get('type') == 'text':
                    return json.loads(content['text'])
            return result

    async def sync(self, rid, dimension, targets, asset_types):
        self.c.store.run(rid)
        if dimension not in ('project', 'task') or not 1 <= len(targets) <= 20:
            raise ValueError('Select 1..20 projects or tasks')
        if not asset_types or any(kind not in ('subdomain', 'service', 'app') for kind in asset_types):
            raise ValueError('Select supported asset types')
        counts = {kind: 0 for kind in asset_types}
        truncated = False
        for target in targets:
            for kind in asset_types:
                for page in range(1, 21):
                    result = await self.call('list_assets', {'asset_type': 'asset' if kind == 'service' else kind,
                        'pageIndex': page, 'pageSize': 100, 'filter': {dimension: [target]}})
                    rows = result.get('list', [])
                    for row in rows:
                        source = 'scopesentry:'+dimension+':'+target
                        if kind == 'subdomain':
                            value = row.get('host')
                        elif kind == 'app':
                            value = row.get('name')
                        else:
                            value = row.get('url') or ':'.join(str(x) for x in (row.get('ip') or row.get('domain'), row.get('port')) if x)
                        if value:
                            asset = self.c.investigation.asset(rid, kind, value, source, metadata=row)
                            counts[kind] += 1
                            if kind == 'subdomain':
                                for ip in row.get('ip') or []:
                                    self.c.investigation.asset(rid, 'ip', ip, source, asset['id'])
                    if len(rows) < 100:
                        break
                    if page == 20:
                        truncated = True
        result = {'counts': counts, 'truncated': truncated, 'synced_at': now(),
                  'scope_unchanged': True}
        self.c.store.event(rid, 'assets.synced', result)
        return result
