from __future__ import annotations

import json
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from .domain import ChallengeInput, Conflict, dump, now, uid
from .filesystem import SecureFiles
from .vendor.engine.competition.models import PlatformConnection
from .vendor.engine.competition.secrets import PlatformSecretStore
from .vendor.engine.platform.contracts.modules import (
    InstanceLeaseRef, PlatformChallengeRef, RemoteArtifactRef, SubmissionRequest, SyncRequest)


class Platforms:
    """Actual migrated Phoenix adapters, bridged into Phoenix challenges and evidence."""
    def __init__(self, components):
        self.c, self.store = components, components.store
        self.secrets = PlatformSecretStore(self.store.root / 'integration-secrets')
        self.adapters = {}
        self.transport = None  # Controlled native HTTP fixtures can inject a transport.

    async def configure(self, kind, endpoint, credential, account='', connection_id=None, label=''):
        if kind not in ('ctfd', 'gzctf', 'rctf'):
            raise ValueError('Supported platforms: ctfd, gzctf, rctf')
        parsed = urlsplit(endpoint)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Specify an HTTP(S) platform endpoint without credentials')
        cid = connection_id or uid('platform')
        old = self.c.investigation.setting('platform:'+cid, {})
        reference = self.secrets.put(cid, 'credential', credential) if credential else old.get('credential_ref')
        if not reference:
            raise ValueError('A platform credential is required')
        connection = PlatformConnection(connection_id=cid, platform_kind=kind,
            canonical_base_url=endpoint.rstrip('/'), account_key=account, credential_ref=reference)
        self.c.investigation.configure('platform:'+cid, {**connection.model_dump(mode='json'), 'label': label or kind.upper()})
        if cid in self.adapters:
            await self.adapters.pop(cid).aclose()
        self.store.audit('platform.configured', {'connection_id': cid, 'kind': kind})
        return {'id': cid, 'label': label or kind.upper(), 'credential_configured': True}

    def connections(self):
        values = self.store.all("SELECT value FROM integration_settings WHERE key LIKE 'platform:%'")
        return [{**{k: v for k, v in json.loads(row['value']).items() if k != 'credential_ref'},
                 'credential_configured': bool(json.loads(row['value']).get('credential_ref'))} for row in values]

    def adapter(self, cid):
        if cid not in self.adapters:
            value = self.c.investigation.setting('platform:'+cid)
            if not value:
                raise ValueError('Unknown platform connection')
            value = {k: v for k, v in value.items() if k != 'label'}
            connection = PlatformConnection.model_validate(value)
            if connection.platform_kind == 'ctfd':
                from .vendor.engine.competition.platforms.ctfd import CTFdAdapter as Adapter
            elif connection.platform_kind == 'gzctf':
                from .vendor.engine.competition.platforms.gzctf import GZCTFAdapter as Adapter
            else:
                from .vendor.engine.competition.platforms.rctf import RCtfAdapter as Adapter
            self.adapters[cid] = Adapter(connection, self.secrets, client_transport=self.transport)
        return self.adapters[cid]

    async def probe(self, cid):
        result = await self.adapter(cid).probe()
        return result.model_dump(mode='json')

    async def sync(self, cid, competition_id=None):
        result = await self.adapter(cid).sync_competition(SyncRequest(connection_id=cid, competition_id=competition_id))
        value = result.model_dump(mode='json')
        self.c.investigation.configure('platform-snapshot:'+cid, {**value, 'competition_id': competition_id, 'synced_at': now()})
        self.store.audit('platform.synced', {'connection_id': cid, 'count': result.synced_challenges})
        return value

    def snapshot(self, cid):
        return self.c.investigation.setting('platform-snapshot:'+cid, {'detail': {'snapshots': []}})

    async def import_challenge(self, cid, key, targets, authorized=True, flag_prefix='flag'):
        snapshots = self.snapshot(cid)
        row = next((s for s in snapshots['detail'].get('snapshots', []) if s['external_challenge_id'] == key), None)
        if not row or row.get('hidden'):
            raise ValueError('Sync and select an available platform challenge first')
        category = row.get('category', '').lower()
        category = {'rev': 'reverse', 're': 'reverse', 'cryptography': 'crypto', '取证': 'forensics'}.get(category, category)
        if category not in ('web', 'crypto', 'pwn', 'reverse', 'forensics', 'misc'):
            category = 'misc'
        challenge = self.store.create_challenge(ChallengeInput(title=row['name'], category=category,
            description=row.get('description') or row['name'], targets=targets, authorized=True, flag_prefix=flag_prefix))
        fs = SecureFiles(self.store.root / 'inputs' / challenge['id'])
        for index, artifact in enumerate(row.get('artifacts', [])):
            location = artifact.get('url') or artifact.get('location') or ''
            if not location:
                detail = row.get('raw_payload', {}).get('detail', {})
                files = list(detail.get('files') or [])
                for field in ('attachment', 'context'):
                    if isinstance(detail.get(field), dict) and detail[field].get('url'):
                        files.append(detail[field])
                if index < len(files):
                    entry = files[index]
                    location = (entry.get('url', '') if isinstance(entry, dict) else str(entry)).split('?', 1)[0]
            remote_id = artifact.get('remote_id') or key
            result = await self.adapter(cid).fetch_artifact(RemoteArtifactRef(connection_id=cid,
                remote_id=remote_id, url=location, sha256=artifact.get('sha256') or None))
            filename = PurePosixPath(artifact.get('filename') or artifact.get('name') or urlsplit(location).path).name
            if not filename:
                filename = f'attachment-{index}'
            fs.write(filename, result.content)
        self.store.execute('INSERT INTO platform_links VALUES(?,?,?,?,?,?,?)',
                           (uid('link'), cid, key, challenge['id'], snapshots.get('competition_id'), dump(row), now()))
        self.store.audit('platform.challenge_imported', {'connection_id': cid, 'challenge_key': key, 'challenge_id': challenge['id']})
        return self.store.challenge(challenge['id'])

    async def submit(self, cid, candidate_id, confirm):
        if not confirm:
            raise ValueError('Explicitly confirm this platform submission')
        candidate = self.store.one('SELECT * FROM candidates WHERE id=?', (candidate_id,))
        run = self.store.run(candidate['run_id'])
        if run['mode'] == 'benchmark':
            raise ValueError('Held-out answers cannot be sent to a competition platform')
        self.c.evidence.read(run['id'], candidate['evidence_id'], 0, 1)
        link = self.store.one('SELECT * FROM platform_links WHERE connection_id=? AND challenge_id=?', (cid, run['challenge_id']))
        sid = uid('submission')
        with self.store.tx() as db:
            existing = db.execute('SELECT * FROM platform_submissions WHERE connection_id=? AND candidate_id=?', (cid, candidate_id)).fetchone()
            if existing:
                return {**dict(existing), 'result': json.loads(existing['result'])}
            db.execute('INSERT INTO platform_submissions VALUES(?,?,?,?,?,?)', (sid, cid, candidate_id, 'pending', '{}', now()))
        try:
            result = await self.adapter(cid).submit(SubmissionRequest(connection_id=cid,
                challenge_key=link['challenge_key'], flag=candidate['value'], idempotency_key=sid))
            value = result.model_dump(mode='json')
            self.store.execute('UPDATE platform_submissions SET state=?,result=? WHERE id=?', (result.status, dump(value), sid))
            if result.status in ('correct', 'incorrect'):
                status = 'accepted' if result.status == 'correct' else 'rejected'
                self.store.execute('UPDATE candidates SET status=?,verification=? WHERE id=?',
                    (status, 'platform receipt '+sid, candidate_id))
                self.store.event(run['id'], 'flag.verified', {'id': candidate_id, 'status': status, 'submission_id': sid})
            return {'id': sid, 'state': result.status, 'result': value}
        except BaseException:
            self.store.execute("UPDATE platform_submissions SET state='unknown' WHERE id=?", (sid,))
            # Never blindly resubmit a flag after an uncertain platform POST.
            raise

    async def instance(self, cid, key, action):
        adapter = self.adapter(cid)
        storage_key = 'platform-lease:'+cid+':'+key
        if action == 'acquire':
            result = await adapter.acquire_instance(PlatformChallengeRef(connection_id=cid, challenge_key=key))
        else:
            saved = self.c.investigation.setting(storage_key)
            if not saved:
                raise Conflict('No saved dynamic instance lease')
            lease = InstanceLeaseRef.model_validate(saved['lease'])
            if action == 'release':
                await adapter.release_instance(lease)
                self.c.investigation.configure(storage_key, None)
                return {'state': 'released'}
            if action != 'renew':
                raise ValueError('Unknown instance action')
            result = await adapter.renew_instance(lease)
        value = result.model_dump(mode='json')
        self.c.investigation.configure(storage_key, value)
        return value

    async def poll_submission(self, cid, sid):
        row = self.store.one('SELECT * FROM platform_submissions WHERE id=? AND connection_id=?', (sid, cid))
        if row['state'] != 'pending':
            return {**row, 'result': json.loads(row['result'])}
        saved = json.loads(row['result'])
        if not saved.get('submission_id'):
            raise Conflict('No remote receipt ID is available; check the platform before resubmitting')
        candidate = self.store.one('SELECT * FROM candidates WHERE id=?', (row['candidate_id'],))
        run = self.store.run(candidate['run_id'])
        link = self.store.one('SELECT challenge_key FROM platform_links WHERE connection_id=? AND challenge_id=?', (cid, run['challenge_id']))
        adapter = self.adapter(cid)
        if not hasattr(adapter, 'poll_submission'):
            raise ValueError('This platform does not provide asynchronous receipt polling')
        game_id, challenge_id = link['challenge_key'].split('/', 1)
        result = await adapter.poll_submission(game_id, challenge_id, saved['submission_id'])
        value = result.model_dump(mode='json')
        self.store.execute('UPDATE platform_submissions SET state=?,result=? WHERE id=?', (result.status, dump(value), sid))
        if result.status in ('correct', 'incorrect'):
            status = 'accepted' if result.status == 'correct' else 'rejected'
            self.store.execute('UPDATE candidates SET status=?,verification=? WHERE id=?', (status, 'platform receipt '+sid, candidate['id']))
            self.store.event(run['id'], 'flag.verified', {'id': candidate['id'], 'status': status, 'submission_id': sid})
        return {'id': sid, 'state': result.status, 'result': value}

    async def shutdown(self):
        for adapter in self.adapters.values():
            await adapter.aclose()
