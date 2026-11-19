"""Native durable effect queue: the single-writer substrate for external side effects.

A side effect that crosses a process boundary (a platform submission, a notification)
is persisted before it runs and drained after the owning transaction commits. A
retryable failure backs off exponentially up to a cap, then dead-letters for an
operator. An uncertain effect is never auto-retried: it dead-letters immediately so a
person reconciles it. State names mirror the platform EffectReceipt contract so the
queue and the command/receipt layer speak one vocabulary.
"""
from __future__ import annotations

import asyncio
import json

from .domain import Conflict, dump, now, uid

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS effects(
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        key TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{}',
        state TEXT NOT NULL DEFAULT 'accepted',
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 8,
        run_after REAL NOT NULL,
        last_error TEXT NOT NULL DEFAULT '',
        destination TEXT NOT NULL DEFAULT '',
        created REAL NOT NULL,
        updated REAL NOT NULL,
        UNIQUE(kind,key))""",
    'CREATE INDEX IF NOT EXISTS effects_due ON effects(state,run_after)',
)

ACTIVE_STATES = ('accepted', 'waiting')
TERMINAL_STATES = ('completed', 'failed', 'dead_letter', 'cancelled')


class Defer(Exception):
    """Retry later without consuming a failure attempt (e.g. a known retry-after window)."""

    def __init__(self, seconds: float):
        super().__init__(f'deferred {seconds}s')
        self.seconds = max(0.0, float(seconds))


class Uncertain(Exception):
    """The effect may or may not have happened; fail closed and surface to an operator."""


class Effects:
    def __init__(self, store, *, base_delay: float = 1.0, max_delay: float = 300.0):
        self.store = store
        self.base_delay, self.max_delay = base_delay, max_delay
        for statement in SCHEMA:
            self.store.execute(statement)

    def enqueue(self, kind: str, key: str, payload: dict | None = None, *,
                run_after: float | None = None, max_attempts: int = 8, destination: str = '') -> str:
        payload = dump(payload or {})
        t = now()
        due = t if run_after is None else run_after
        with self.store.tx() as db:
            row = db.execute('SELECT id,state FROM effects WHERE kind=? AND key=?', (kind, key)).fetchone()
            if row and row['state'] in ACTIVE_STATES:
                # Coalesce: the latest intent wins, but an in-flight backoff is preserved.
                db.execute('UPDATE effects SET payload=?,run_after=?,destination=?,updated=? WHERE id=?',
                           (payload, due, destination, t, row['id']))
                return row['id']
            if row:
                db.execute("UPDATE effects SET payload=?,state='accepted',attempts=0,max_attempts=?,run_after=?,"
                           "last_error='',destination=?,updated=? WHERE id=?",
                           (payload, max_attempts, due, destination, t, row['id']))
                return row['id']
            eid = uid('effect')
            db.execute('INSERT INTO effects(id,kind,key,payload,state,attempts,max_attempts,run_after,destination,'
                       'created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (eid, kind, key, payload, 'accepted', 0, max_attempts, due, destination, t, t))
            return eid

    def get(self, eid: str) -> dict:
        row = self.store.one('SELECT * FROM effects WHERE id=?', (eid,))
        row['payload'] = json.loads(row['payload'])
        return row

    def list(self, *, kind: str | None = None, state: str | None = None, limit: int = 200) -> list[dict]:
        sql, args = 'SELECT * FROM effects WHERE 1=1', []
        if kind:
            sql += ' AND kind=?'
            args.append(kind)
        if state:
            sql += ' AND state=?'
            args.append(state)
        sql += ' ORDER BY updated DESC LIMIT ?'
        args.append(limit)
        rows = self.store.all(sql, tuple(args))
        for row in rows:
            row['payload'] = json.loads(row['payload'])
        return rows

    async def drain(self, handlers: dict, *, limit: int = 32, kinds: list[str] | None = None,
                    keys: list[str] | None = None) -> list[dict]:
        sql, args = "SELECT * FROM effects WHERE state IN ('accepted','waiting') AND run_after<=?", [now()]
        if kinds:
            sql += ' AND kind IN (%s)' % ','.join('?' * len(kinds))
            args += list(kinds)
        if keys:
            sql += ' AND key IN (%s)' % ','.join('?' * len(keys))
            args += list(keys)
        sql += ' ORDER BY run_after,created LIMIT ?'
        args.append(limit)
        results = []
        for row in self.store.all(sql, tuple(args)):
            handler = handlers.get(row['kind'])
            if handler:
                results.append(await self._run(row, handler))
        return results

    async def _run(self, row: dict, handler) -> dict:
        eid, key = row['id'], row['key']
        claimed = self.store.execute("UPDATE effects SET state='running',updated=? WHERE id=? "
                                     "AND state IN ('accepted','waiting')", (now(), eid))
        if not claimed:
            return {'id': eid, 'key': key, 'state': 'skipped'}
        try:
            output = await handler(json.loads(row['payload']))
        except Defer as exc:
            self.store.execute("UPDATE effects SET state='waiting',run_after=?,updated=? WHERE id=?",
                               (now() + exc.seconds, now(), eid))
            return {'id': eid, 'key': key, 'state': 'waiting'}
        except Uncertain as exc:
            reason = f'uncertain: {str(exc)[:600]}'
            self._dead_letter(eid, reason)
            return {'id': eid, 'key': key, 'state': 'dead_letter', 'error': reason, 'uncertain': True}
        except asyncio.CancelledError:
            # Leave it running; recover() dead-letters it so a person reconciles the uncertainty.
            raise
        except Exception as exc:
            reason = f'{type(exc).__name__}: {str(exc)[:600]}'
            attempts = row['attempts'] + 1
            if attempts >= row['max_attempts']:
                self._dead_letter(eid, reason, attempts=attempts)
                return {'id': eid, 'key': key, 'state': 'dead_letter', 'error': reason, 'uncertain': False}
            delay = min(self.max_delay, self.base_delay * (2 ** (attempts - 1)))
            self.store.execute("UPDATE effects SET state='waiting',attempts=?,run_after=?,last_error=?,updated=? "
                               'WHERE id=?', (attempts, now() + delay, reason, now(), eid))
            return {'id': eid, 'key': key, 'state': 'waiting', 'attempts': attempts}
        self.store.execute("UPDATE effects SET state='completed',attempts=?,last_error='',updated=? WHERE id=?",
                           (row['attempts'] + 1, now(), eid))
        return {'id': eid, 'key': key, 'state': 'completed', 'output': output}

    def _dead_letter(self, eid: str, reason: str, attempts: int | None = None):
        if attempts is None:
            self.store.execute("UPDATE effects SET state='dead_letter',last_error=?,updated=? WHERE id=?",
                               (reason, now(), eid))
        else:
            self.store.execute("UPDATE effects SET state='dead_letter',attempts=?,last_error=?,updated=? WHERE id=?",
                               (attempts, reason, now(), eid))

    def retry(self, eid: str) -> dict:
        row = self.store.one('SELECT state FROM effects WHERE id=?', (eid,))
        if row['state'] not in ('dead_letter', 'failed', 'cancelled'):
            raise Conflict('Only a dead-lettered, failed or cancelled effect can be retried')
        self.store.execute("UPDATE effects SET state='accepted',attempts=0,run_after=?,last_error='',updated=? "
                           'WHERE id=?', (now(), now(), eid))
        self.store.audit('effect.retried', {'id': eid})
        return self.get(eid)

    def drop(self, eid: str) -> dict:
        row = self.store.one('SELECT state FROM effects WHERE id=?', (eid,))
        if row['state'] in ('completed', 'cancelled'):
            raise Conflict('This effect is already settled')
        self.store.execute("UPDATE effects SET state='cancelled',updated=? WHERE id=?", (now(), eid))
        self.store.audit('effect.dropped', {'id': eid})
        return self.get(eid)

    def health(self) -> list[dict]:
        kinds: dict[str, dict] = {}
        for row in self.store.all('SELECT kind,state,COUNT(*) AS n FROM effects GROUP BY kind,state'):
            counts = kinds.setdefault(row['kind'], {s: 0 for s in
                                      ('accepted', 'waiting', 'running', 'completed', 'failed', 'dead_letter', 'cancelled')})
            counts[row['state']] = row['n']
        return [{'kind': kind, **counts, 'needs_attention': counts['dead_letter'] + counts['failed']}
                for kind, counts in sorted(kinds.items())]

    def recover(self):
        # Fail closed: an effect running at crash time may already have happened externally.
        self.store.execute("UPDATE effects SET state='dead_letter',last_error='interrupted while running; "
                           "reconcile before retry',updated=? WHERE state='running'", (now(),))


async def effects_loop(c, stop_event: asyncio.Event, interval: float = 2.0):
    while not stop_event.is_set():
        try:
            await c.effects.drain(c.effect_handlers)
        except Exception as exc:
            c.store.audit('effects.drain_error', {'reason': f'{type(exc).__name__}: {str(exc)[:600]}'})
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass