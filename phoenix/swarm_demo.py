"""Deterministic parallel integration fixture, never a model-capability benchmark."""
from __future__ import annotations

import asyncio
import base64
import json

from .demo import DemonstrationProvider
from .domain import BudgetSpec, ChallengeInput, Lesson, Quote, RunInput, digest
from .filesystem import SecureFiles
from .providers import ModelGateway
from .runtime import Runtime


class SwarmDemonstrationProvider(DemonstrationProvider):
    def __init__(self):
        self.inflight = 0
        self.peak = 0
        self.models: set[str] = set()
        self.worker_inflight = 0
        self.peak_workers = 0
        self.reviewer_saw_facts = False

    async def complete(self, profile, messages, tools):
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        self.models.add(profile.model)
        if tools:
            self.worker_inflight += 1
            self.peak_workers = max(self.peak_workers, self.worker_inflight)
        try:
            await asyncio.sleep(0.025)
            return self.reply(messages, tools)
        finally:
            self.inflight -= 1
            if tools:
                self.worker_inflight -= 1

    def reply(self, messages, tools):
        core = next((json.loads(m['content']) for m in messages if m['role'] == 'user'
                     and isinstance(m.get('content'), str) and m['content'].startswith('{')
                     and 'challenge' in m['content']), {})
        if not tools:
            if core.get('existing_tasks'):
                return self.text({'rationale': 'The fixture needs no additional tasks', 'tasks': [], 'stop': True})
            return self.text({'rationale': 'SCRIPTED fixture: independent branches then evidence handoff', 'tasks': [
                {'key': 'inspect', 'goal': 'Inspect metadata without executing attachments', 'role': 'analyst'},
                {'key': 'decode', 'goal': 'Decode the original base64 payload and share a cited observation', 'role': 'solver'},
                {'key': 'review', 'goal': 'Read producer evidence after both branches finish', 'role': 'reviewer',
                 'depends_on': ['inspect', 'decode']},
            ], 'stop': False})
        intent = core.get('your_intent', {})
        key = intent.get('key')
        results = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
        if key == 'review':
            facts = core.get('recent_shared_facts', [])
            self.reviewer_saw_facts = len(facts) >= 2
            if not results:
                cite = next(q for f in facts for q in f['citations'])
                return self.call('evidence_read', {'evidence_id': cite['evidence_id']})
            return self.call('task_finish', {'summary': 'SCRIPTED review: both branches finished and original evidence was read',
                                            'evidence_ids': [json.loads(results[0]['output'])['id']], 'outcome': 'done'})
        if not results:
            return self.call('file_read', {'path': 'input:metadata.txt' if key == 'inspect' else 'input:payload.txt'})
        output = json.loads(results[0]['output'])
        if key == 'decode' and len(results) == 1:
            return self.call('decode', {'operation': 'base64', 'data': output['content'].strip()})
        original = results[1] if key == 'decode' else results[0]
        fact_at = 2 if key == 'decode' else 1
        if len(results) == fact_at:
            return self.call('fact_record', {
                'statement': 'Decoded payload contains a candidate; a shaped string is not acceptance' if key == 'decode'
                             else 'The provided metadata identifies a scripted base64 exercise',
                'stance': 'observation',
                'citations': [{'evidence_id': original['evidence_id'], 'quote': '"text"' if key == 'decode' else '"content"'}],
            })
        return self.call('task_finish', {'summary': 'Original tool output and cited observation are available to peers',
                                        'evidence_ids': [original['evidence_id']], 'outcome': 'done'})


async def create_swarm_demo(c):
    store = c.store
    challenge = store.create_challenge(ChallengeInput(title='Phoenix swarm / SCRIPTED integration demo', category='misc',
        description='SCRIPTED FIXTURE, NOT A LIVE MODEL BENCHMARK. Two branches share evidence, then a reviewer reads it.',
        authorized=True))
    flag = 'flag{phoenix_parallel_evidence_handoff}'
    fs = SecureFiles(store.root / 'inputs' / challenge['id'])
    fs.write('payload.txt', base64.b64encode(flag.encode()))
    fs.write('metadata.txt', b'encoding=base64; mode=SCRIPTED; no external service')
    run = store.create_run(challenge['id'], RunInput(auto_distill=False, max_rounds=2,
        budget=BudgetSpec(max_tokens=500000, max_calls=40, wall_seconds=120)), mode='demo')
    provider = SwarmDemonstrationProvider()
    runtime = Runtime(store, c.settings, ModelGateway(store, c.settings, provider), c.tools, c.memory, c.knowledge)
    await runtime.run(run['id'])
    # Register the test oracle only after the dependency and review chain completes.
    store.execute('INSERT INTO verifiers VALUES(?,?)', (challenge['id'], digest(flag)))
    candidates = store.all('SELECT id FROM candidates WHERE run_id=?', (run['id'],))
    for candidate in candidates:
        c.evidence.verify(candidate['id'])
    if candidates and runtime.accepted(run['id']) and all(t['state'] == 'done' for t in store.tasks(run['id'])):
        store.state(run['id'], 'solved', 'SCRIPTED fixture: exact fixture oracle accepted after the full handoff')
    store.event(run['id'], 'swarm.demo_result', {'scripted': True, 'peak_concurrent_requests': provider.peak,
                                               'peak_concurrent_worker_requests': provider.peak_workers,
                                               'reviewer_saw_shared_facts': provider.reviewer_saw_facts})
    c.memory.consolidate_episode(run['id'])
    evidence = store.one("SELECT id FROM evidence WHERE run_id=? AND tool='decode'", (run['id'],))
    c.memory.propose(run['id'], Lesson(title='Parallel evidence handoff (SCRIPTED fixture)', category='misc', kind='observation',
        applicability='This fixture checks plumbing only; it is not evidence of real model problem-solving ability.',
        steps=['Keep original observations referenced by evidence ID.', 'Read shared observations after task dependencies complete.'],
        pitfalls=['Do not use scripted demos to authorize a strategy promotion.'],
        citations=[Quote(evidence_id=evidence['id'], quote='"text"')]))
    return store.run(run['id'])
