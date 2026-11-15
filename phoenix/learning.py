from __future__ import annotations

import json

from .domain import Conflict, Quote, RunInput, SkillSpec, dump, now, uid
from .evolution import BenchmarkSuite


class LearningCycle:
    """An operator-authorized autonomous learning cycle, with measured promotion.

    A draft lesson is allowed into a quarantined candidate but never into active
    retrieval before a passing real-model held-out evaluation. No self-rating gate.
    """
    def __init__(self, components):
        self.c = components

    async def execute(self, rid: str, suite: BenchmarkSuite, config: RunInput,
                      auto_promote: bool = False) -> dict:
        c, s = self.c, self.c.store
        run = s.run(rid)
        if run['state'] in ('created', 'running', 'distilling', 'paused', 'interrupted') or run['mode'] == 'benchmark':
            raise Conflict('Learning requires a completed non-benchmark source episode')
        if s.all("SELECT id FROM learning_cycles WHERE run_id=? AND state='running'", (rid,)):
            raise Conflict('A learning cycle already owns this source episode')
        lid = uid('learn')
        policy = {'auto_promote': auto_promote, 'suite': suite.name, 'run_budget': config.model_dump(),
                  'maximum_benchmark_runs': len(suite.cases) * suite.repetitions * 2}
        s.execute('INSERT INTO learning_cycles VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (lid, rid, 'running', dump(policy), '[]', '[]', '[]', '{}', now(), None))
        try:
            sources = s.all('SELECT m.* FROM memories m JOIN memory_sources x ON x.memory_id=m.id '
                            "WHERE x.run_id=? AND m.state IN ('draft','active') ORDER BY "
                            "CASE m.kind WHEN 'procedure' THEN 0 WHEN 'negative' THEN 1 ELSE 2 END,m.created", (rid,))
            if not sources:
                s.state(rid, 'distilling', 'Learning cycle: extracting evidence-backed proposals')
                try:
                    await c.memory.distill(rid, c.gateway)
                finally:
                    s.state(rid, run['state'], run['reason'])
                    c.memory.consolidate_episode(rid)
                sources = s.all('SELECT m.* FROM memories m JOIN memory_sources x ON x.memory_id=m.id '
                                "WHERE x.run_id=? AND m.state IN ('draft','active') ORDER BY m.created", (rid,))
            if not sources:
                raise ValueError('No valid evidence-backed lesson was produced; nothing can be evolved')
            # One candidate per cycle keeps experiments interpretable and limits combinatorial cost.
            memory = sources[0]
            body = json.loads(memory['body'])
            key = memory['category'] + '-baseline'
            active = s.one("SELECT * FROM skills WHERE key=? AND state='active'", (key,))
            baseline = SkillSpec.model_validate_json(active['spec'])
            instructions = baseline.instructions[:8] + [
                'Conditional lesson; apply only under these preconditions: ' + body['applicability']]
            instructions += ['Under those preconditions: ' + step for step in body['steps'][:6]]
            spec = SkillSpec(key=key, category=memory['category'], applicability=baseline.applicability,
                             instructions=instructions[:16], stop_conditions=(baseline.stop_conditions + body['pitfalls'])[:8],
                             memory_ids=list(dict.fromkeys(baseline.memory_ids + [memory['id']])))
            candidate = c.evolution.propose(spec, allow_draft_for_evaluation=True)
            s.execute('UPDATE learning_cycles SET memory_ids=?,skill_ids=? WHERE id=?',
                      (dump([memory['id']]), dump([candidate['id']]), lid))
            evaluation = await c.evaluator.evaluate(candidate['id'], suite, config)
            report = json.loads(evaluation['report'])
            report['promotion_requested'] = auto_promote
            report['promoted'] = False
            if auto_promote and evaluation['mode'] == 'live' and report['eligible']:
                # Validate before changing the active memory corpus.
                for source in s.all('SELECT * FROM memory_sources WHERE memory_id=?', (memory['id'],)):
                    c.evidence.validate_quotes(source['run_id'], [Quote.model_validate(x)
                        for x in json.loads(source['citations'])])
                was_active = memory['state'] == 'active'
                c.memory.review(memory['id'], True, reviewer='heldout-evaluation:' + evaluation['id'])
                try:
                    c.evolution.promote(candidate['id'], evaluation['id'])
                except BaseException:
                    if not was_active:
                        c.memory.review(memory['id'], False, reviewer='promotion-rollback')
                        s.execute("UPDATE memories SET state='draft' WHERE id=?", (memory['id'],))
                    raise
                report['promoted'] = True
            report['candidate_id'] = candidate['id']
            report['memory_id'] = memory['id']
            s.execute("UPDATE learning_cycles SET state='completed',evaluation_ids=?,report=?,ended=? WHERE id=?",
                      (dump([evaluation['id']]), dump(report), now(), lid))
            s.audit('learning.completed', {'cycle_id': lid, 'source_run': rid, 'promoted': report['promoted']})
        except BaseException as exc:
            s.execute("UPDATE learning_cycles SET state='interrupted',report=?,ended=? WHERE id=?",
                      (dump({'error': type(exc).__name__, 'detail': str(exc)[:800]}), now(), lid))
            raise
        return s.one('SELECT * FROM learning_cycles WHERE id=?', (lid,))
