from __future__ import annotations

import asyncio
import json

from pydantic import Field, field_validator

from .domain import (BudgetSpec, Category, ChallengeInput, Conflict, RunInput, Strict, dump, now, uid)

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS competitions(
        id TEXT PRIMARY KEY,
        connection_id TEXT NOT NULL,
        external_competition_id TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        policy TEXT NOT NULL,
        scheduler_state TEXT NOT NULL DEFAULT 'paused',
        created REAL NOT NULL,
        updated REAL NOT NULL,
        UNIQUE(connection_id,external_competition_id))""",
    """CREATE TABLE IF NOT EXISTS competition_queue(
        id TEXT PRIMARY KEY,
        competition_id TEXT NOT NULL REFERENCES competitions(id),
        challenge_key TEXT NOT NULL,
        title TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'misc',
        state TEXT NOT NULL DEFAULT 'pending',
        priority INTEGER NOT NULL DEFAULT 50,
        score REAL NOT NULL DEFAULT 0,
        admission_decision TEXT NOT NULL DEFAULT '{}',
        run_id TEXT,
        challenge_id TEXT,
        submission_id TEXT,
        submission_state TEXT,
        last_error TEXT NOT NULL DEFAULT '',
        created REAL NOT NULL,
        updated REAL NOT NULL,
        UNIQUE(competition_id,challenge_key))""",
    'CREATE INDEX IF NOT EXISTS competition_queue_state ON competition_queue(competition_id,state)',
)

CATEGORY_ALIASES = {'rev': 'reverse', 're': 'reverse', 'cryptography': 'crypto', '取证': 'forensics'}
# Native terminal run states mapped onto the queue entry outcome.
TERMINAL_RUN_STATES = {'solved': 'solved', 'exhausted': 'exhausted', 'budget_exhausted': 'exhausted',
                       'awaiting_verification': 'exhausted', 'failed': 'failed'}
SETTLED_ENTRY_STATES = ('solved', 'exhausted', 'failed')


def native_category(value: str) -> str:
    category = CATEGORY_ALIASES.get((value or '').lower(), (value or '').lower())
    return category if category in ('web', 'crypto', 'pwn', 'reverse', 'forensics', 'misc') else 'misc'


class CompetitionPolicy(Strict):
    max_concurrency: int = Field(default=2, ge=1, le=16)
    categories: list[Category] = Field(default_factory=list, max_length=6)
    auto_submit: bool = False
    auto_import: bool = True
    auto_distill: bool = False
    flag_prefix: str = Field(default='flag', pattern=r'^[A-Za-z0-9_]{1,32}$')
    targets: list[str] = Field(default_factory=list, max_length=20)
    budget: BudgetSpec = Field(default_factory=BudgetSpec)

    @field_validator('targets')
    @classmethod
    def _targets(cls, values: list[str]) -> list[str]:
        return ChallengeInput.validate_targets(values)


class Competitions:
    """Native competition batch scheduler bridging platform snapshots to native solving runs."""

    def __init__(self, components):
        self.c, self.store = components, components.store
        for statement in SCHEMA:
            self.store.execute(statement)

    def _row(self, competition_id: str) -> dict:
        return self.store.one('SELECT * FROM competitions WHERE id=?', (competition_id,))

    def _entry(self, competition_id: str, entry_id: str) -> dict:
        return self.store.one('SELECT * FROM competition_queue WHERE id=? AND competition_id=?',
                              (entry_id, competition_id))

    def _policy(self, competition: dict) -> CompetitionPolicy:
        return CompetitionPolicy.model_validate(json.loads(competition['policy']))

    def _counts(self) -> dict:
        counts: dict[str, dict] = {}
        for row in self.store.all('SELECT competition_id,state,COUNT(*) AS n FROM competition_queue '
                                  'GROUP BY competition_id,state'):
            counts.setdefault(row['competition_id'], {})[row['state']] = row['n']
        return counts

    def _summary(self, competition: dict, counts: dict) -> dict:
        value = {k: v for k, v in competition.items() if k != 'policy'}
        value['policy'] = json.loads(competition['policy'])
        value['counts'] = counts.get(competition['id'], {})
        return value

    def register(self, connection_id: str, title: str, external_competition_id: str = '',
                 policy: dict | None = None) -> dict:
        if connection_id not in {p['connection_id'] for p in self.c.platforms.connections()}:
            raise ValueError('Unknown platform connection; configure it first')
        if not title.strip():
            raise ValueError('A competition title is required')
        if self.store.all('SELECT id FROM competitions WHERE connection_id=? AND external_competition_id=?',
                          (connection_id, external_competition_id)):
            raise Conflict('This competition is already registered for the connection')
        value = CompetitionPolicy.model_validate(policy or {}).model_dump(mode='json')
        cid, t = uid('comp'), now()
        self.store.execute('INSERT INTO competitions VALUES(?,?,?,?,?,?,?,?)',
                           (cid, connection_id, external_competition_id, title.strip()[:180], dump(value),
                            'paused', t, t))
        self.store.audit('competition.registered', {'id': cid, 'connection_id': connection_id, 'title': title})
        return self.describe(cid)

    def list(self) -> list[dict]:
        counts = self._counts()
        return [self._summary(row, counts)
                for row in self.store.all('SELECT * FROM competitions ORDER BY created DESC')]

    def describe(self, competition_id: str) -> dict:
        competition = self._row(competition_id)
        value = self._summary(competition, self._counts())
        value['queue'] = self.queue(competition_id)
        return value

    def remove(self, competition_id: str) -> dict:
        self._row(competition_id)
        with self.store.tx() as db:
            db.execute('DELETE FROM competition_queue WHERE competition_id=?', (competition_id,))
            db.execute('DELETE FROM competitions WHERE id=?', (competition_id,))
        self.store.audit('competition.removed', {'id': competition_id})
        return {'removed': competition_id}

    async def sync(self, competition_id: str) -> dict:
        competition = self._row(competition_id)
        connection_id = competition['connection_id']
        result = await self.c.platforms.sync(connection_id, competition['external_competition_id'] or None)
        snapshot = self.c.platforms.snapshot(connection_id)
        rows = snapshot.get('detail', {}).get('snapshots', [])
        added = updated = 0
        for row in rows:
            if row.get('hidden'):
                continue
            key = str(row.get('external_challenge_id') or '')
            if not key:
                continue
            title = str(row.get('name') or key)[:180]
            category = native_category(row.get('category', ''))
            score = float(row.get('points') or 0)
            existing = self.store.all('SELECT id FROM competition_queue WHERE competition_id=? AND challenge_key=?',
                                      (competition_id, key))
            if existing:
                self.store.execute('UPDATE competition_queue SET title=?,category=?,score=?,updated=? WHERE id=?',
                                   (title, category, score, now(), existing[0]['id']))
                updated += 1
            else:
                self.store.execute('INSERT INTO competition_queue(id,competition_id,challenge_key,title,category,'
                                   'score,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                                   (uid('cq'), competition_id, key, title, category, score, now(), now()))
                added += 1
        external = snapshot.get('detail', {}).get('external_competition_id')
        if external and not competition['external_competition_id']:
            self.store.execute('UPDATE competitions SET external_competition_id=?,updated=? WHERE id=?',
                               (str(external)[:300], now(), competition_id))
        self.store.audit('competition.synced', {'id': competition_id, 'added': added, 'updated': updated})
        return {'added': added, 'updated': updated, 'visible': len(rows),
                'synced_challenges': result.get('synced_challenges', 0)}

    def set_policy(self, competition_id: str, policy: dict) -> dict:
        self._row(competition_id)
        value = CompetitionPolicy.model_validate(policy).model_dump(mode='json')
        self.store.execute('UPDATE competitions SET policy=?,updated=? WHERE id=?', (dump(value), now(), competition_id))
        self.store.audit('competition.policy_updated', {'id': competition_id, 'policy': value})
        return self.describe(competition_id)

    def scheduler(self, competition_id: str, action: str) -> dict:
        competition = self._row(competition_id)
        if action in ('start', 'resume'):
            if competition['scheduler_state'] != 'paused':
                raise Conflict('The scheduler is already running')
            state = 'running'
        elif action == 'pause':
            if competition['scheduler_state'] != 'running':
                raise Conflict('The scheduler is not running')
            state = 'paused'
        else:
            raise ValueError('Unknown scheduler action')
        self.store.execute('UPDATE competitions SET scheduler_state=?,updated=? WHERE id=?',
                           (state, now(), competition_id))
        self.store.audit('competition.scheduler', {'id': competition_id, 'action': action, 'state': state})
        return self.describe(competition_id)

    def queue(self, competition_id: str) -> list[dict]:
        self._row(competition_id)
        rows = self.store.all('SELECT q.*, r.state AS run_state, r.reason AS run_reason '
                              'FROM competition_queue q LEFT JOIN runs r ON r.id=q.run_id '
                              'WHERE q.competition_id=? ORDER BY q.priority DESC,q.score DESC,q.created',
                              (competition_id,))
        for row in rows:
            row['admission_decision'] = json.loads(row['admission_decision'])
        return rows

    def set_priority(self, competition_id: str, entry_id: str, priority: int) -> dict:
        self._entry(competition_id, entry_id)
        self.store.execute('UPDATE competition_queue SET priority=?,updated=? WHERE id=?',
                           (priority, now(), entry_id))
        return self._entry(competition_id, entry_id)

    def skip(self, competition_id: str, entry_id: str) -> dict:
        entry = self._entry(competition_id, entry_id)
        if entry['state'] == 'running':
            raise Conflict('Pause or finish the bound run before skipping this entry')
        self.store.execute("UPDATE competition_queue SET state='skipped',admission_decision=?,updated=? WHERE id=?",
                           (dump({'action': 'skip', 'reason': 'operator'}), now(), entry_id))
        self.store.audit('competition.entry_skipped', {'competition_id': competition_id, 'id': entry_id})
        return self._entry(competition_id, entry_id)

    def requeue(self, competition_id: str, entry_id: str) -> dict:
        entry = self._entry(competition_id, entry_id)
        if entry['state'] == 'running':
            raise Conflict('This entry still has an active run')
        self.store.execute("UPDATE competition_queue SET state='pending',run_id=NULL,submission_id=NULL,"
                           "submission_state=NULL,last_error='',admission_decision=?,updated=? WHERE id=?",
                           (dump({'action': 'requeue', 'reason': 'operator'}), now(), entry_id))
        self.store.audit('competition.entry_requeued', {'competition_id': competition_id, 'id': entry_id})
        return self._entry(competition_id, entry_id)

    async def admit(self, competition_id: str, entry_id: str) -> dict:
        competition = self._row(competition_id)
        entry = self._entry(competition_id, entry_id)
        if entry['state'] == 'running':
            raise Conflict('This entry already has an active run')
        await self._admit(competition, self._policy(competition), entry, force=True)
        return self._entry(competition_id, entry_id)

    async def tick(self, competition_id: str) -> dict:
        competition = self._row(competition_id)
        policy = self._policy(competition)
        result: dict = {'competition_id': competition_id, 'admitted': [], 'settled': [],
                        'submitted': [], 'errors': []}
        bound = self.store.all('SELECT * FROM competition_queue WHERE competition_id=? AND run_id IS NOT NULL '
                               "AND state NOT IN ('pending','skipped') ORDER BY created", (competition_id,))
        for entry in bound:
            try:
                await self._reconcile(competition, policy, entry, result)
            except Exception as exc:
                self._record_error(entry, exc, result)
        if competition['scheduler_state'] == 'running':
            active = self.store.one("SELECT COUNT(*) AS n FROM competition_queue WHERE competition_id=? "
                                    "AND state='running'", (competition_id,))['n']
            slots = policy.max_concurrency - active
            if slots > 0:
                pending = self.store.all("SELECT * FROM competition_queue WHERE competition_id=? AND state='pending' "
                                         'ORDER BY priority DESC,score DESC,created', (competition_id,))
                for entry in pending:
                    if slots <= 0:
                        break
                    try:
                        if await self._admit(competition, policy, entry) == 'admit':
                            slots -= 1
                            result['admitted'].append(entry['id'])
                    except Exception as exc:
                        self._record_error(entry, exc, result, failed=True)
        self.store.execute('UPDATE competitions SET updated=? WHERE id=?', (now(), competition_id))
        return result

    async def _admit(self, competition: dict, policy: CompetitionPolicy, entry: dict,
                     force: bool = False) -> str:
        connection_id = competition['connection_id']
        if not force and policy.categories and entry['category'] not in policy.categories:
            self._decision(entry, 'hold', 'category_filtered')
            return 'hold'
        link = self.store.all('SELECT challenge_id FROM platform_links WHERE connection_id=? AND challenge_key=?',
                              (connection_id, entry['challenge_key']))
        if link:
            challenge = self.store.challenge(link[0]['challenge_id'])
        elif policy.auto_import:
            challenge = await self.c.platforms.import_challenge(connection_id, entry['challenge_key'],
                                                                policy.targets, True, policy.flag_prefix)
        else:
            if force:
                raise Conflict('Enable auto-import or import this challenge from the platform workspace first')
            self._decision(entry, 'hold', 'auto_import_disabled')
            return 'hold'
        config = RunInput(budget=policy.budget, auto_distill=policy.auto_distill)
        self.c.runtime.swarm.validate(config, challenge['category'], require_models=True)
        for role in ('planner', 'distiller'):
            if role == 'distiller' and not config.auto_distill:
                continue
            if not self.c.settings.profile(role).model:
                raise ValueError(f'Model profile for {role} is not configured')
        run = self.store.create_run(challenge['id'], config)
        self.c.runtime.swarm.ensure(run['id'])
        self.c.runtime.launch(run['id'])
        self.store.execute("UPDATE competition_queue SET state='running',run_id=?,challenge_id=?,last_error='',"
                           'admission_decision=?,updated=? WHERE id=?',
                           (run['id'], challenge['id'],
                            dump({'action': 'admit', 'run_id': run['id'], 'challenge_id': challenge['id']}),
                            now(), entry['id']))
        self.store.event(run['id'], 'competition.admitted',
                         {'competition_id': competition['id'], 'queue_id': entry['id'],
                          'challenge_key': entry['challenge_key']})
        return 'admit'

    async def _reconcile(self, competition: dict, policy: CompetitionPolicy, entry: dict, result: dict):
        run = self.store.run(entry['run_id'])
        if entry['state'] == 'running':
            outcome = TERMINAL_RUN_STATES.get(run['state'])
            if not outcome:
                return
            self.store.execute('UPDATE competition_queue SET state=?,admission_decision=?,updated=? WHERE id=?',
                               (outcome, dump({'action': 'settled', 'run_state': run['state'],
                                               'reason': run['reason']}), now(), entry['id']))
            self.store.event(run['id'], 'competition.settled',
                             {'competition_id': competition['id'], 'queue_id': entry['id'], 'state': outcome})
            result['settled'].append(entry['id'])
            entry = {**entry, 'state': outcome}
        if entry['state'] not in SETTLED_ENTRY_STATES or not policy.auto_submit or entry['submission_id']:
            return
        candidate = self.store.all("SELECT id FROM candidates WHERE run_id=? AND status='accepted' "
                                   'ORDER BY created LIMIT 1', (run['id'],))
        if not candidate:
            return
        receipt = await self.c.platforms.submit(competition['connection_id'], candidate[0]['id'], True)
        self.store.execute('UPDATE competition_queue SET submission_id=?,submission_state=?,updated=? WHERE id=?',
                           (receipt['id'], receipt['state'], now(), entry['id']))
        self.store.event(run['id'], 'competition.submitted',
                         {'competition_id': competition['id'], 'queue_id': entry['id'],
                          'candidate_id': candidate[0]['id'], 'submission_id': receipt['id'],
                          'state': receipt['state']})
        result['submitted'].append(entry['id'])

    def _decision(self, entry: dict, action: str, reason: str):
        self.store.execute('UPDATE competition_queue SET admission_decision=?,updated=? WHERE id=?',
                           (dump({'action': action, 'reason': reason}), now(), entry['id']))

    def _record_error(self, entry: dict, exc: Exception, result: dict, failed: bool = False):
        reason = f'{type(exc).__name__}: {str(exc)[:600]}'
        state = "state='failed'," if failed else ''
        self.store.execute(f"UPDATE competition_queue SET {state} last_error=?,admission_decision=?,updated=? "
                           'WHERE id=?', (reason, dump({'action': 'error', 'reason': reason}), now(), entry['id']))
        result['errors'].append({'id': entry['id'], 'reason': reason})
        self.store.audit('competition.entry_error', {'id': entry['id'], 'reason': reason})


async def competition_loop(c, stop_event: asyncio.Event, interval: float = 5.0):
    while not stop_event.is_set():
        for competition in c.competitions.list():
            if competition['scheduler_state'] != 'running':
                continue
            try:
                await c.competitions.tick(competition['id'])
            except Exception as exc:
                c.store.audit('competition.tick_error',
                              {'id': competition['id'], 'reason': f'{type(exc).__name__}: {str(exc)[:600]}'})
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass