from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager, closing
from pathlib import Path
from typing import Any

from .domain import ChallengeInput, Conflict, NotFound, Plan, RunInput, digest, dump, now, uid


class Store:
    """SQLite/WAL journal. Every claim/budget transition is transactional."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'phoenix.sqlite3'
        self.lock = threading.RLock()
        with closing(self.connect()) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(Path(__file__).with_name('schema.sql').read_text())
            version = db.execute('SELECT version FROM schema_version').fetchone()[0]
            if version != 1:
                raise RuntimeError(f'Unsupported database version {version}')

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=15000')
        return db

    @contextmanager
    def tx(self):
        with self.lock:
            db = self.connect()
            try:
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def all(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self.lock, closing(self.connect()) as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict[str, Any]:
        rows = self.all(sql, args)
        if not rows:
            raise NotFound('Record not found')
        return rows[0]

    def execute(self, sql: str, args: tuple = ()) -> int:
        with self.tx() as db:
            return db.execute(sql, args).rowcount

    def audit(self, action: str, payload: dict):
        self.execute('INSERT INTO audit(action,payload,created) VALUES(?,?,?)', (action, dump(payload), now()))

    def event(self, run_id: str, kind: str, payload: dict, task_id: str | None = None):
        self.execute('INSERT INTO events(run_id,task_id,kind,payload,created) VALUES(?,?,?,?,?)',
                     (run_id, task_id, kind, dump(payload), now()))

    def create_challenge(self, spec: ChallengeInput) -> dict:
        cid = uid('ch')
        self.execute('INSERT INTO challenges(id,title,category,description,targets,authorized,flag_prefix,created) '
                     'VALUES(?,?,?,?,?,?,?,?)',
                     (cid, spec.title, spec.category, spec.description, dump(spec.targets), 1, spec.flag_prefix, now()))
        (self.root / 'inputs' / cid).mkdir(parents=True)
        return self.challenge(cid)

    def challenge(self, cid: str) -> dict:
        row = self.one('SELECT * FROM challenges WHERE id=?', (cid,))
        row['targets'] = json.loads(row['targets'])
        return row

    def freeze(self, cid: str) -> str:
        c = self.challenge(cid)
        files = []
        root = self.root / 'inputs' / cid
        for p in sorted(root.rglob('*')):
            if p.is_symlink():
                raise ValueError('Symbolic links are not accepted as challenge inputs')
            if p.is_file():
                files.append([p.relative_to(root).as_posix(), digest(p.read_bytes())])
        signature = digest(dump({'description': c['description'], 'category': c['category'], 'files': files}))
        self.execute('UPDATE challenges SET frozen=1,input_hash=? WHERE id=?', (signature, cid))
        return signature

    def create_run(self, cid: str, config: RunInput, *, mode: str = 'live', skills: list[str] | None = None,
                   knowledge_snapshot: list[str] | None = None) -> dict:
        self.freeze(cid)
        if skills is None:
            cat = self.challenge(cid)['category']
            skills = [r['id'] for r in self.all("SELECT id FROM skills WHERE state='active' AND "
                                               "json_extract(spec,'$.category')=?", (cat,))]
        if knowledge_snapshot is None:
            knowledge_snapshot = [x['id'] for x in self.all("SELECT id FROM documents WHERE trust='trusted'")]
        rid = uid('run')
        t = now()
        self.execute('INSERT INTO runs(id,challenge_id,state,config,skills,knowledge_snapshot,created,updated,mode) '
                     'VALUES(?,?,?,?,?,?,?,?,?)',
                     (rid, cid, 'created', dump(config.model_dump()), dump(skills), dump(knowledge_snapshot), t, t, mode))
        self.event(rid, 'run.created', {'mode': mode, 'skill_snapshot': skills})
        return self.run(rid)

    def run(self, rid: str) -> dict:
        r = self.one('SELECT * FROM runs WHERE id=?', (rid,))
        for key in ('config', 'skills', 'knowledge_snapshot'):
            r[key] = json.loads(r[key])
        return r

    def run_profile(self, rid: str, role: str) -> dict | None:
        rows = self.all('SELECT profile FROM run_profiles WHERE run_id=? AND role=?', (rid, role))
        return json.loads(rows[0]['profile']) if rows else None

    def state(self, rid: str, state: str, reason: str = ''):
        self.execute('UPDATE runs SET state=?,reason=?,updated=? WHERE id=?', (state, reason, now(), rid))
        self.event(rid, 'run.state', {'state': state, 'reason': reason})

    def add_plan(self, rid: str, plan: Plan) -> list[str]:
        """Validate the whole DAG before committing any node; dependencies are task keys."""
        with self.tx() as db:
            old = [dict(x) for x in db.execute('SELECT * FROM tasks WHERE run_id=?', (rid,))]
            if len(old) + len(plan.tasks) > 64:
                raise ValueError('A run may contain at most 64 task nodes')
            keys = {r['key'] for r in old}
            incoming = [t.key for t in plan.tasks]
            if len(set(incoming)) != len(incoming) or keys.intersection(incoming):
                raise ValueError('Duplicate task key')
            graph = {r['key']: json.loads(r['dependencies']) for r in old}
            graph.update({t.key: t.depends_on for t in plan.tasks})
            visiting, done = set(), set()

            def walk(key: str):
                if key in visiting:
                    raise ValueError('Dependency cycle')
                if key in done:
                    return
                if key not in graph:
                    raise ValueError(f'Unknown dependency {key}')
                visiting.add(key)
                for dep in graph[key]:
                    walk(dep)
                visiting.remove(key)
                done.add(key)

            for key in graph:
                walk(key)
            existing_fp = {r['fingerprint'] for r in old}
            ids = []
            for t in plan.tasks:
                fp = digest(' '.join(t.goal.lower().split()))
                if fp in existing_fp:
                    raise ValueError('Duplicate exploration goal; use an explicitly different hypothesis')
                existing_fp.add(fp)
                tid = uid('task')
                db.execute('INSERT INTO tasks(id,run_id,key,goal,role,dependencies,priority,state,fingerprint) '
                           'VALUES(?,?,?,?,?,?,?,?,?)',
                           (tid, rid, t.key, t.goal, t.role, dump(t.depends_on), t.priority, 'pending', fp))
                ids.append(tid)
        self.event(rid, 'plan.added', {'rationale': plan.rationale, 'task_ids': ids})
        return ids

    def tasks(self, rid: str) -> list[dict]:
        rows = self.all('SELECT * FROM tasks WHERE run_id=? ORDER BY priority DESC,rowid', (rid,))
        for r in rows:
            r['dependencies'] = json.loads(r['dependencies'])
        return rows

    def claim(self, rid: str, owner: str, *, roles: list[str] | None = None,
              worker_id: str | None = None) -> dict | None:
        with self.tx() as db:
            run = db.execute('SELECT state FROM runs WHERE id=?', (rid,)).fetchone()
            if not run or run[0] != 'running':
                return None
            if worker_id:
                worker = db.execute('SELECT enabled FROM swarm_workers WHERE run_id=? AND worker_id=?',
                                    (rid, worker_id)).fetchone()
                if not worker or not worker['enabled']:
                    return None
                busy = db.execute("SELECT 1 FROM tasks t JOIN swarm_assignments a ON a.task_id=t.id AND a.attempt=t.attempt "
                                  "WHERE t.run_id=? AND a.worker_id=? AND t.state='running'",
                                  (rid, worker_id)).fetchone()
                if busy:
                    return None
            rows = [dict(r) for r in db.execute('SELECT * FROM tasks WHERE run_id=? '
                                               'ORDER BY priority DESC,rowid', (rid,))]
            states = {r['key']: r['state'] for r in rows}
            for row in rows:
                if row['state'] != 'pending':
                    continue
                deps = json.loads(row['dependencies'])
                if any(states[d] in ('failed', 'blocked', 'cancelled') for d in deps):
                    db.execute("UPDATE tasks SET state='blocked',ended=? WHERE id=?", (now(), row['id']))
                    continue
                if worker_id and row['attempt']:
                    prior = db.execute('SELECT worker_id FROM swarm_assignments WHERE task_id=? AND attempt=?',
                                       (row['id'], row['attempt'])).fetchone()
                    if prior and prior['worker_id'] != worker_id:
                        continue
                if roles is not None and row['role'] not in roles:
                    continue
                if not all(states[d] == 'done' for d in deps):
                    continue
                db.execute("UPDATE tasks SET state='running',owner=?,started=?,attempt=attempt+1 WHERE id=?",
                           (owner, now(), row['id']))
                if worker_id:
                    db.execute('INSERT INTO swarm_assignments VALUES(?,?,?,?)',
                               (row['id'], row['attempt'] + 1, rid, worker_id))
                row.update(state='running', owner=owner, dependencies=deps, attempt=row['attempt'] + 1)
                return row
        return None

    def finish(self, tid: str, owner: str, state: str, summary: str):
        changed = self.execute("UPDATE tasks SET state=?,summary=?,ended=? WHERE id=? AND owner=? AND state='running'",
                               (state, summary, now(), tid, owner))
        if changed != 1:
            raise Conflict('Stale task owner or task is already terminal')

    def append_message(self, tid: str, message: dict):
        self.execute('INSERT INTO messages(task_id,payload) VALUES(?,?)', (tid, dump(message)))

    def messages(self, tid: str) -> list[dict]:
        return [json.loads(r['payload']) for r in self.all('SELECT payload FROM messages WHERE task_id=? ORDER BY seq',
                                                         (tid,))]

    def recover(self) -> list[str]:
        """Crash recovery is fail-closed: never replay an uncertain tool automatically."""
        with self.tx() as db:
            ids = [x[0] for x in db.execute("SELECT id FROM runs WHERE state IN ('running','distilling')")]
            db.execute("UPDATE tasks SET state='interrupted' WHERE state='running'")
            db.execute("UPDATE runs SET state='interrupted',reason='Process interrupted; inspect executions before resume' "
                       "WHERE state IN ('running','distilling')")
            db.execute("UPDATE model_calls SET status='uncertain' WHERE status='reserved'")
            db.execute("UPDATE executions SET state='uncertain' WHERE state='running'")
            db.execute("UPDATE evaluations SET state='interrupted' WHERE state='running'")
            db.execute("UPDATE learning_cycles SET state='interrupted' WHERE state='running'")
            db.execute("UPDATE engine_sessions SET state='interrupted' WHERE state='running'")
            db.execute("UPDATE terminal_sessions SET state='interrupted' WHERE state='open'")
            db.execute("UPDATE request_approvals SET state='cancelled' WHERE state='pending'")
        return ids

    def resume(self, rid: str, acknowledge_uncertain: bool):
        if not acknowledge_uncertain:
            raise ValueError('Explicit acknowledgement of uncertain side effects is required')
        with self.tx() as db:
            row = db.execute('SELECT state FROM runs WHERE id=?', (rid,)).fetchone()
            if not row or row[0] not in ('interrupted', 'paused'):
                raise Conflict('Only interrupted or paused runs can resume')
            if db.execute("SELECT 1 FROM executions WHERE run_id=? AND state IN ('running','uncertain')", (rid,)).fetchone():
                raise Conflict('Reconcile sandbox executions before resuming')
            db.execute("UPDATE tasks SET state='pending',owner='' WHERE run_id=? AND state='interrupted'", (rid,))
            db.execute("UPDATE runs SET state='created',reason='',owner='' WHERE id=?", (rid,))
        self.event(rid, 'run.resume_acknowledged', {'uncertain_tools_may_have_run': True})
