from __future__ import annotations

import base64
import json
from pathlib import Path

from pydantic import Field, field_validator

from .domain import ChallengeInput, Conflict, RunInput, SkillSpec, Strict, digest, dump, now, uid
from .filesystem import SecureFiles
from .memory import redact
from .runtime import Runtime
from .store import Store


class BenchmarkCase(Strict):
    name: str = Field(min_length=3, max_length=180)
    category: str
    description: str = Field(min_length=5, max_length=12000)
    files_base64: dict[str, str] = Field(default_factory=dict)
    expected_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    split: str = 'heldout'

    @field_validator('split')
    @classmethod
    def must_be_heldout(cls, value):
        if value != 'heldout':
            raise ValueError('Evolution evaluations require heldout cases')
        return value


class BenchmarkSuite(Strict):
    name: str
    cases: list[BenchmarkCase] = Field(min_length=3, max_length=100)
    repetitions: int = Field(default=1, ge=1, le=5)


class Evolution:
    """Versioned prompt/procedure evolution with an executable paired benchmark gate.

    No model can directly promote itself, replace core code, mutate its tool privileges,
    or turn its own rating into an evaluation result.
    """
    def __init__(self, store: Store):
        self.store = store

    def propose(self, spec: SkillSpec, *, allow_draft_for_evaluation: bool = False) -> dict:
        sources = []
        for mid in spec.memory_ids:
            memory = self.store.one('SELECT * FROM memories WHERE id=?', (mid,))
            if memory['state'] not in (('active', 'draft') if allow_draft_for_evaluation else ('active',)):
                raise ValueError('Skill candidates may only cite reviewed active memories')
            sources.extend(self.store.all('SELECT run_id FROM memory_sources WHERE memory_id=?', (mid,)))
        # Obvious secrets/answer literals cannot be used as a learned strategy.
        serialized = dump(spec.model_dump())
        if redact(serialized) != serialized:
            raise ValueError('Skill contains flags, target URLs or likely secrets; generalize them first')
        with self.store.tx() as db:
            rows = db.execute('SELECT * FROM skills WHERE key=? ORDER BY version DESC', (spec.key,)).fetchall()
            active = next((r for r in rows if r['state'] == 'active'), None)
            version = rows[0]['version'] + 1 if rows else 1
            sid = uid('skill')
            db.execute('INSERT INTO skills VALUES(?,?,?,?,?,?,?,?)',
                       (sid, spec.key, version, serialized, digest(serialized),
                        active['id'] if active else None, 'candidate', now()))
        self.store.audit('skill.proposed', {'skill_id': sid, 'source_count': len(sources)})
        return self.store.one('SELECT * FROM skills WHERE id=?', (sid,))

    def from_memory(self, mid: str, key: str) -> dict:
        row = self.store.one('SELECT * FROM memories WHERE id=?', (mid,))
        body = json.loads(row['body'])
        spec = SkillSpec(key=key, category=row['category'], applicability=body['applicability'],
                         instructions=body['steps'], stop_conditions=body['pitfalls'], memory_ids=[mid])
        return self.propose(spec)

    def install_seed(self, spec: SkillSpec) -> str:
        existing = self.store.all('SELECT id FROM skills WHERE key=?', (spec.key,))
        if existing:
            return existing[0]['id']
        row = self.propose(spec)
        self.store.execute("UPDATE skills SET state='active' WHERE id=?", (row['id'],))
        self.store.audit('skill.seed_baseline', {'skill_id': row['id'], 'note': 'Initial authored baseline, not evolved'})
        return row['id']

    def promote(self, sid: str, evaluation_id: str) -> dict:
        with self.store.tx() as db:
            skill = db.execute('SELECT * FROM skills WHERE id=?', (sid,)).fetchone()
            evaluation = db.execute('SELECT * FROM evaluations WHERE id=? AND skill_id=?', (evaluation_id, sid)).fetchone()
            if not skill or skill['state'] != 'candidate' or not evaluation:
                raise Conflict('Missing candidate or matching evaluation')
            report = json.loads(evaluation['report'])
            if evaluation['mode'] != 'live' or evaluation['state'] != 'completed' or not report.get('eligible'):
                raise Conflict('Only a completed real-model, held-out, passing benchmark can promote a strategy')
            if report.get('candidate_sha256') != skill['sha256']:
                raise Conflict('The evaluated candidate content has changed')
            active = db.execute("SELECT id FROM skills WHERE key=? AND state='active'", (skill['key'],)).fetchone()
            active_id = active[0] if active else None
            if active_id != evaluation['baseline_id']:
                raise Conflict('Baseline changed after evaluation; rerun the paired comparison')
            db.execute("UPDATE skills SET state='retired' WHERE key=? AND state='active'", (skill['key'],))
            db.execute("UPDATE skills SET state='active' WHERE id=?", (sid,))
        self.store.audit('skill.promoted', {'skill_id': sid, 'evaluation_id': evaluation_id})
        return self.store.one('SELECT * FROM skills WHERE id=?', (sid,))

    def rollback(self, sid: str):
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM skills WHERE id=?', (sid,)).fetchone()
            if not row or row['state'] != 'retired':
                raise Conflict('Only a previously active retired version can be restored')
            db.execute("UPDATE skills SET state='retired' WHERE key=? AND state='active'", (row['key'],))
            db.execute("UPDATE skills SET state='active' WHERE id=?", (sid,))
        self.store.audit('skill.rollback', {'skill_id': sid})


class Evaluator:
    def __init__(self, store: Store, runtime: Runtime):
        self.store, self.runtime = store, runtime

    async def evaluate(self, sid: str, suite: BenchmarkSuite, config: RunInput) -> dict:
        skill = self.store.one('SELECT * FROM skills WHERE id=?', (sid,))
        if skill['state'] != 'candidate':
            raise ValueError('Only candidate strategies can be evaluated')
        spec = SkillSpec.model_validate_json(skill['spec'])
        if any(c.category != spec.category for c in suite.cases):
            raise ValueError('Use a category-matched held-out suite for the candidate strategy')
        baseline_rows = self.store.all("SELECT id FROM skills WHERE key=? AND state='active'", (skill['key'],))
        baseline_id = baseline_rows[0]['id'] if baseline_rows else None
        common = [r['id'] for r in self.store.all("SELECT id FROM skills WHERE key<>? AND state='active' "
                                                 "AND json_extract(spec,'$.category')=?", (skill['key'], spec.category))]
        # Freeze knowledge for both arms; never include benchmark episodes or future memory updates.
        snapshot = [r['id'] for r in self.store.all("SELECT id FROM documents WHERE trust='trusted'")]
        train_hashes = {r['input_hash'] for r in self.store.all('SELECT DISTINCT input_hash FROM memory_sources')}
        for mid in spec.memory_ids:
            train_hashes.update(r['input_hash'] for r in self.store.all(
                'SELECT input_hash FROM memory_sources WHERE memory_id=?', (mid,)))
        cases = []
        seen = set()
        for case in suite.cases:
            challenge = self.store.create_challenge(ChallengeInput(title=case.name, category=case.category,
                                                    description=case.description, authorized=True))
            fs = SecureFiles(self.store.root / 'inputs' / challenge['id'])
            for name, encoded in case.files_base64.items():
                fs.write(name, base64.b64decode(encoded, validate=True))
            signature = self.store.freeze(challenge['id'])
            if signature in train_hashes or signature in seen:
                raise ValueError('Train/test contamination or duplicate held-out input detected')
            seen.add(signature)
            self.store.execute('INSERT INTO verifiers VALUES(?,?)', (challenge['id'], case.expected_sha256))
            cases.append((case, challenge['id']))
        eid, mode = uid('eval'), 'live' if self.runtime.gateway.live else 'fixture'
        self.store.execute('INSERT INTO evaluations VALUES(?,?,?,?,?,?,?,?,?)',
                           (eid, sid, baseline_id, 'running', digest(dump(suite.model_dump())), mode, '{}', now(), None))
        report = {'candidate_sha256': skill['sha256'], 'baseline_id': baseline_id, 'cases': [], 'eligible': False,
                  'knowledge_snapshot': snapshot, 'model_snapshot': self.runtime.settings.public()['profiles'],
                  'repetitions': suite.repetitions,
                  'cost_prices_configured': all(p.input_usd_per_million is not None and p.output_usd_per_million is not None
                                                for p in self.runtime.settings.profiles.values()),
                  'qualification': 'Engineering gate; not a leaderboard claim'}
        config = config.model_copy(update={'auto_distill': False})
        try:
            for case_index, (case, cid) in enumerate(cases):
                for repetition in range(suite.repetitions):
                    # Alternate order to reduce simple ordering/cache bias; not statistical proof.
                    arms = ['baseline', 'candidate'] if (case_index + repetition) % 2 == 0 else ['candidate', 'baseline']
                    result = {'name': case.name, 'repetition': repetition}
                    for arm in arms:
                        skills = common + ([sid] if arm == 'candidate' else ([baseline_id] if baseline_id else []))
                        run = self.store.create_run(cid, config, mode='benchmark', skills=skills, knowledge_snapshot=snapshot)
                        final = await self.runtime.run(run['id'])
                        exact = self.store.all("SELECT id FROM candidates WHERE run_id=? AND status='accepted' "
                                               "AND verification='operator-supplied exact SHA-256 verifier'", (run['id'],))
                        result[arm] = {'run_id': run['id'], 'solved': bool(exact), 'state': final['state'],
                                       'tokens': final['billed_tokens'] + final['held_tokens'],
                                       'wall_seconds': max(0, now() - final['created']),
                                       'cost_usd': final['billed_usd'] + final['held_usd'],
                                       'uncertain_calls': len(self.store.all("SELECT id FROM model_calls WHERE run_id=? "
                                                                           "AND status='uncertain'", (run['id'],)))}
                    report['cases'].append(result)
                    self.store.execute('UPDATE evaluations SET report=? WHERE id=?', (dump(report), eid))
            report.update(self.gate(report['cases']))
            if mode != 'live':
                report['eligible'] = False
                report['gate_reasons'].append('Fixture/simulated models cannot authorize promotion')
            self.store.execute("UPDATE evaluations SET state='completed',report=?,ended=? WHERE id=?",
                               (dump(report), now(), eid))
        except BaseException:
            self.store.execute("UPDATE evaluations SET state='interrupted',report=?,ended=? WHERE id=?",
                               (dump(report), now(), eid))
            raise
        return self.store.one('SELECT * FROM evaluations WHERE id=?', (eid,))

    @staticmethod
    def gate(cases: list[dict]) -> dict:
        unique = len({x['name'] for x in cases})
        baseline = sum(int(x['baseline']['solved']) for x in cases)
        candidate = sum(int(x['candidate']['solved']) for x in cases)
        regressions = sum(x['baseline']['solved'] and not x['candidate']['solved'] for x in cases)
        bt = sum(x['baseline']['tokens'] for x in cases)
        ct = sum(x['candidate']['tokens'] for x in cases)
        bc = sum(x['baseline']['cost_usd'] for x in cases)
        cc = sum(x['candidate']['cost_usd'] for x in cases)
        uncertain = sum(x[a].get('uncertain_calls', 0) for x in cases for a in ('baseline', 'candidate'))
        reasons = []
        if unique < 3:
            reasons.append('At least three distinct held-out cases are required')
        if regressions:
            reasons.append('At least one previously solved case regressed')
        improved = candidate > baseline or (candidate == baseline and candidate > 0 and bt > 0 and ct <= bt * 0.9)
        if not improved:
            reasons.append('No solve-count improvement or >=10% token improvement at equal nonzero solves')
        if bc > 0 and cc > 1.25 * bc:
            reasons.append('Cost increased by more than 25%')
        if uncertain:
            reasons.append('Uncertain billed calls prevent a trustworthy comparison')
        return {'eligible': not reasons, 'gate_reasons': reasons, 'baseline_solved': baseline,
                'candidate_solved': candidate, 'regressions': regressions,
                'baseline_tokens': bt, 'candidate_tokens': ct, 'distinct_cases': unique}
