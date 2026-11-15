"""Native, evidence-sharing swarm: no delegation to a legacy daemon or CLI.

Worker identity is separate from role and model. Each run snapshots the roster
and credential *environment names*, never credential values. Model profiles are
frozen for workers so pause/resume cannot silently switch their protocols.
"""
from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import Field

from .config import ModelProfile, Settings, WorkerProfile
from .domain import Conflict, RunInput, Strict, dump, now
from .store import Store


class Swarm:
    def __init__(self, store: Store, settings: Settings):
        self.store, self.settings = store, settings

    def selected(self, config: dict, category: str) -> list[WorkerProfile]:
        ids = config.get('worker_ids', [])
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate worker selections')
        known = {w.id: w for w in self.settings.workers}
        if set(ids) - set(known):
            raise ValueError('Unknown worker IDs')
        result = [w for w in self.settings.workers if w.enabled and (not ids or w.id in ids)
                  and (not w.categories or category in w.categories)]
        if not result:
            raise ValueError('No enabled swarm workers match the selected category')
        return result

    def validate(self, config: RunInput, category: str, require_models: bool = False):
        workers = self.selected(config.model_dump(), category)
        for worker in workers:
            for role in worker.roles:
                profile = self.settings.profiles[worker.profile] if worker.profile else self.settings.profile(role)
                if require_models and not profile.model:
                    raise ValueError(f'Model is not configured for worker {worker.id} / {role}')
        return workers

    def ensure(self, rid: str):
        with self.store.tx() as db:
            for role in ('planner', 'distiller'):
                db.execute('INSERT OR IGNORE INTO run_profiles VALUES(?,?,?,?)',
                           (rid, role, dump(self.settings.profile(role).model_dump()), now()))
        if self.store.all('SELECT worker_id FROM swarm_workers WHERE run_id=?', (rid,)):
            return
        run = self.store.run(rid)
        category = self.store.challenge(run['challenge_id'])['category']
        selected = self.selected(run['config'], category)
        with self.store.tx() as db:
            for worker in selected:
                profiles = {role: (self.settings.profiles[worker.profile] if worker.profile
                                   else self.settings.profile(role)).model_dump() for role in worker.roles}
                db.execute('INSERT OR IGNORE INTO swarm_workers VALUES(?,?,?,?,?,?)',
                           (rid, worker.id, dump(worker.model_dump()), dump(profiles), 1, now()))
        self.store.event(rid, 'swarm.initialized', {'workers': [w.id for w in selected],
                                                  'concurrency': run['config']['concurrency']})

    def roster(self, rid: str) -> list[dict]:
        rows = self.store.all('SELECT * FROM swarm_workers WHERE run_id=? ORDER BY created,worker_id', (rid,))
        for row in rows:
            row['spec'] = json.loads(row['spec'])
            row['profiles'] = json.loads(row['profiles'])
        return rows

    def claim(self, rid: str, owner: str) -> dict | None:
        for worker in self.roster(rid):
            if not worker['enabled']:
                continue
            task = self.store.claim(rid, owner, roles=worker['spec']['roles'], worker_id=worker['worker_id'])
            if task:
                task['_worker'] = worker['spec']
                task['_profile'] = worker['profiles'][task['role']]
                self.store.event(rid, 'swarm.assigned', {
                    'worker_id': worker['worker_id'], 'role': task['role'],
                    'model': task['_profile']['model'], 'attempt': task['attempt'],
                }, task['id'])
                return task
        return None

    def block_unserviceable(self, rid: str):
        roles = {role for row in self.roster(rid) if row['enabled'] for role in row['spec']['roles']}
        enabled_ids = {w['worker_id'] for w in self.roster(rid) if w['enabled']}
        for task in self.store.tasks(rid):
            prior = self.store.all('SELECT worker_id FROM swarm_assignments WHERE task_id=? AND attempt=?',
                                   (task['id'], task['attempt']))
            affinity_unavailable = bool(prior and prior[0]['worker_id'] not in enabled_ids)
            if task['state'] == 'pending' and (task['role'] not in roles or affinity_unavailable):
                changed = self.store.execute("UPDATE tasks SET state='blocked',summary=?,ended=? "
                                             "WHERE id=? AND state='pending'", (
                    'No enabled worker supports this role; planner must choose another approach', now(), task['id']))
                if changed:
                    self.store.event(rid, 'swarm.unserviceable', {'role': task['role']}, task['id'])

    def add(self, rid: str, spec: WorkerProfile):
        run = self.store.run(rid)
        self.ensure(rid)
        if run['state'] not in ('created', 'running', 'paused', 'interrupted'):
            raise Conflict('Cannot add a worker to a terminal run')
        if spec.categories and self.store.challenge(run['challenge_id'])['category'] not in spec.categories:
            raise ValueError('Worker does not support this challenge category')
        if spec.profile and spec.profile not in self.settings.profiles:
            raise ValueError('Unknown model profile')
        profiles = {role: (self.settings.profiles[spec.profile] if spec.profile
                          else self.settings.profile(role)).model_dump() for role in spec.roles}
        if run['mode'] == 'live' and any(not p['model'] for p in profiles.values()):
            raise ValueError('Configure the model profile before adding this worker')
        with self.store.tx() as db:
            if db.execute('SELECT COUNT(*) FROM swarm_workers WHERE run_id=?', (rid,)).fetchone()[0] >= 32:
                raise Conflict('The per-run roster limit is 32')
            if db.execute('SELECT 1 FROM swarm_workers WHERE run_id=? AND worker_id=?', (rid, spec.id)).fetchone():
                raise Conflict('Worker ID already belongs to this run')
            db.execute('INSERT INTO swarm_workers VALUES(?,?,?,?,?,?)',
                       (rid, spec.id, dump(spec.model_dump()), dump(profiles), int(spec.enabled), now()))
        self.store.event(rid, 'swarm.worker_added', {'worker_id': spec.id, 'roles': spec.roles})
        return self.describe(rid)

    def enabled(self, rid: str, wid: str, enabled: bool):
        if self.store.run(rid)['state'] not in ('created', 'running', 'paused', 'interrupted'):
            raise Conflict('Terminal swarm is immutable')
        self.store.one('SELECT worker_id FROM swarm_workers WHERE run_id=? AND worker_id=?', (rid, wid))
        self.store.execute('UPDATE swarm_workers SET enabled=? WHERE run_id=? AND worker_id=?', (enabled, rid, wid))
        # Drain, never claim that an in-flight tool has been killed.
        self.store.event(rid, 'swarm.worker_enabled', {'worker_id': wid, 'enabled': enabled, 'inflight_policy': 'drain'})
        return self.describe(rid)

    def concurrency(self, rid: str, value: int):
        if not 1 <= value <= 16:
            raise ValueError('Concurrency must be between 1 and 16')
        with self.store.tx() as db:
            row = db.execute('SELECT state,config FROM runs WHERE id=?', (rid,)).fetchone()
            if not row or row['state'] not in ('created', 'running', 'paused', 'interrupted'):
                raise Conflict('Concurrency can only change for resumable runs')
            config = json.loads(row['config'])
            config['concurrency'] = value
            db.execute('UPDATE runs SET config=?,updated=? WHERE id=?', (dump(config), now(), rid))
        self.store.event(rid, 'swarm.scaled', {'concurrency': value, 'inflight_policy': 'drain'})
        return self.describe(rid)

    def describe(self, rid: str) -> dict:
        run = self.store.run(rid)
        tasks = self.store.tasks(rid)
        assignments = self.store.all('SELECT * FROM swarm_assignments WHERE run_id=?', (rid,))
        assigned = {(a['task_id'], a['attempt']): a['worker_id'] for a in assignments}
        rows = []
        for row in self.roster(rid):
            wid = row['worker_id']
            mine = [t for t in tasks if assigned.get((t['id'], t['attempt'])) == wid]
            current = [t for t in mine if t['state'] == 'running']
            usage = self.store.one('''SELECT COUNT(*) AS calls,COALESCE(SUM(input_tokens),0) AS input_tokens,
                COALESCE(SUM(output_tokens),0) AS output_tokens,SUM(cost_usd) AS priced_cost_usd,
                COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END),0) AS unpriced_calls
                FROM model_calls m JOIN swarm_calls c ON c.call_id=m.id WHERE c.run_id=? AND c.worker_id=?''',
                (rid, wid))
            rows.append({'id': wid, **row['spec'], 'enabled': bool(row['enabled']),
                         'profiles': row['profiles'],
                         'status': 'draining' if current and not row['enabled'] else 'working' if current else
                         'disabled' if not row['enabled'] else 'standby' if run['state'] in ('created','running')
                         else 'paused' if run['state'] in ('paused','interrupted') else 'finished',
                         'active_task_ids': [t['id'] for t in current], 'task_ids': [t['id'] for t in mine],
                         'completed': sum(t['state'] == 'done' for t in mine),
                         'failed': sum(t['state'] in ('failed','blocked') for t in mine), 'usage': usage})
        for task in tasks:
            task['worker_id'] = assigned.get((task['id'], task['attempt']))
        return {'run_id': rid, 'concurrency': run['config']['concurrency'], 'workers': rows,
                'tasks': tasks, 'assignments': assignments, 'shared_memory': True,
                'live_workers': sum(w['status'] in ('working','draining') for w in rows)}


class EnableWorker(Strict):
    enabled: bool


class ScaleSwarm(Strict):
    concurrency: int = Field(ge=1, le=16)


def attach_swarm(app, c):
    router = APIRouter(prefix='/api')

    @router.get('/swarm/catalog')
    async def catalog():
        return {'workers': [w.model_dump() for w in c.settings.workers],
                'profiles': c.settings.public()['profiles'], 'roles': c.settings.roles,
                'max_concurrency': 16, 'max_roster': 32}

    @router.get('/runs/{rid}/swarm')
    async def details(rid: str):
        return c.runtime.swarm.describe(rid)

    @router.post('/runs/{rid}/swarm/workers')
    async def add_worker(rid: str, spec: WorkerProfile):
        return c.runtime.swarm.add(rid, spec)

    @router.patch('/runs/{rid}/swarm/workers/{wid}')
    async def enable_worker(rid: str, wid: str, spec: EnableWorker):
        return c.runtime.swarm.enabled(rid, wid, spec.enabled)

    @router.patch('/runs/{rid}/swarm')
    async def scale(rid: str, spec: ScaleSwarm):
        return c.runtime.swarm.concurrency(rid, spec.concurrency)

    app.include_router(router)
