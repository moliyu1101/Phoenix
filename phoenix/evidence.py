from __future__ import annotations

import hmac
import json
import re

from .domain import Quote, digest, dump, now, uid
from .store import Store


class EvidenceStore:
    def __init__(self, store: Store, max_bytes: int = 2 * 1024 * 1024):
        self.store, self.max_bytes = store, max_bytes

    def record(self, rid: str, tid: str | None, tool: str, args: dict, content: str,
               origin: str = 'tool', ok: bool = True, truncated: bool = False) -> dict:
        encoded = content.encode()
        capped = len(encoded) > self.max_bytes
        if capped:
            content = encoded[:self.max_bytes].decode('utf-8', 'replace')
        eid = uid('ev')
        self.store.execute('INSERT INTO evidence(id,run_id,task_id,tool,arguments,sha256,content,origin,truncated,ok,created) '
                           'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (eid, rid, tid, tool, dump(args), digest(content), content, origin,
                            int(capped or truncated), int(ok), now()))
        row = self.store.one('SELECT * FROM evidence WHERE id=?', (eid,))
        self.store.event(rid, 'evidence.created', {'id': eid, 'tool': tool, 'sha256': row['sha256'],
                                                  'ok': ok, 'truncated': bool(row['truncated'])}, tid)
        return row

    def read(self, rid: str, eid: str, offset: int = 0, limit: int = 12000) -> dict:
        row = self.store.one('SELECT * FROM evidence WHERE id=? AND run_id=?', (eid, rid))
        if not hmac.compare_digest(digest(row['content']), row['sha256']):
            raise ValueError('Evidence integrity check failed')
        if offset < 0 or limit < 1 or limit > 64000:
            raise ValueError('Invalid evidence page')
        full = row.pop('content')
        row['content'] = full[offset:offset + limit]
        row['offset'], row['total_chars'] = offset, len(full)
        row['next_offset'] = offset + limit if offset + limit < len(full) else None
        return row

    def validate_quotes(self, rid: str, quotes: list[Quote], require_success: bool = False):
        for q in quotes:
            row = self.store.one('SELECT * FROM evidence WHERE id=? AND run_id=?', (q.evidence_id, rid))
            if row['origin'] not in ('tool', 'sandbox', 'target'):
                raise ValueError('A memory must cite original observations, not model or knowledge echoes')
            if require_success and not row['ok']:
                raise ValueError('This evidence records a tool error')
            if digest(row['content']) != row['sha256'] or q.quote not in row['content']:
                raise ValueError('Citation does not match the immutable observation')

    def fact(self, rid: str, tid: str, statement: str, stance: str, quotes: list[Quote]) -> str:
        if stance not in ('observation', 'hypothesis', 'disproven'):
            raise ValueError('Invalid stance')
        if not quotes:
            raise ValueError('Facts require citations; unsupported assertions are not facts')
        self.validate_quotes(rid, quotes)
        fid = uid('fact')
        self.store.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?)',
                           (fid, rid, tid, statement[:6000], stance, dump([q.model_dump() for q in quotes]), now()))
        self.store.event(rid, 'fact.created', {'id': fid, 'statement': statement, 'stance': stance}, tid)
        return fid

    def scan_flags(self, row: dict) -> list[str]:
        # Evidence proves occurrence, not correctness. The verifier is independent of the model.
        if row['origin'] not in ('tool', 'sandbox', 'target') or not row['ok']:
            return []
        challenge = self.store.challenge(self.store.run(row['run_id'])['challenge_id'])
        pattern = re.escape(challenge['flag_prefix']) + r'\{[^{}\r\n]{1,240}\}'
        found = list(dict.fromkeys(re.findall(pattern, row['content'])))[:20]
        ids = []
        for value in found:
            # Reject direct reflected literals supplied as tool input, including echo/print.
            if value in row['arguments']:
                continue
            cid = uid('flag')
            self.store.execute('INSERT OR IGNORE INTO candidates(id,run_id,evidence_id,value,status,created) VALUES(?,?,?,?,?,?)',
                               (cid, row['run_id'], row['id'], value, 'unverified', now()))
            existing = self.store.one('SELECT * FROM candidates WHERE run_id=? AND value=?', (row['run_id'], value))
            ids.append(existing['id'])
            self.verify(existing['id'])
        return ids

    def verify(self, cid: str) -> dict:
        candidate = self.store.one('SELECT * FROM candidates WHERE id=?', (cid,))
        self.read(candidate['run_id'], candidate['evidence_id'], 0, 1)
        challenge_id = self.store.run(candidate['run_id'])['challenge_id']
        verifiers = self.store.all('SELECT expected_sha256 FROM verifiers WHERE challenge_id=?', (challenge_id,))
        if not verifiers:
            return candidate
        accepted = hmac.compare_digest(digest(candidate['value']), verifiers[0]['expected_sha256'])
        status = 'accepted' if accepted else 'rejected'
        self.store.execute('UPDATE candidates SET status=?,verification=? WHERE id=?',
                           (status, 'operator-supplied exact SHA-256 verifier', cid))
        self.store.event(candidate['run_id'], 'flag.verified', {'id': cid, 'status': status})
        return self.store.one('SELECT * FROM candidates WHERE id=?', (cid,))

    def operator_receipt(self, cid: str, accepted: bool, receipt: str):
        if len(receipt.strip()) < 8:
            raise ValueError('A platform receipt or explanation is required')
        row = self.store.one('SELECT * FROM candidates WHERE id=?', (cid,))
        if self.store.run(row['run_id'])['mode'] == 'benchmark':
            raise ValueError('Manual receipts cannot influence benchmark results')
        self.store.execute('UPDATE candidates SET status=?,verification=? WHERE id=?',
                           ('accepted' if accepted else 'rejected', 'operator receipt: ' + receipt[:4000], cid))
        self.store.audit('flag.operator_receipt', {'candidate_id': cid, 'accepted': accepted, 'receipt': receipt})
