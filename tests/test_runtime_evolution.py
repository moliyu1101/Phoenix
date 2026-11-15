import asyncio
import base64
import json

import pytest

from phoenix.demo import DemonstrationProvider, create_demo
from phoenix.domain import ChallengeInput, Conflict, RunInput, SkillSpec, digest
from phoenix.evolution import BenchmarkCase, BenchmarkSuite, Evaluator
from phoenix.filesystem import SecureFiles
from phoenix.providers import ModelGateway


async def test_real_native_pipeline_with_scripted_model(components):
    result=await create_demo(components)
    assert result['state']=='solved' and result['mode']=='demo'
    assert result['calls']>=4
    candidate=components.store.one('SELECT * FROM candidates WHERE run_id=?',(result['id'],))
    assert candidate['status']=='accepted'
    assert 'exact SHA-256' in candidate['verification']
    assert components.store.one('SELECT COUNT(*) AS n FROM evidence WHERE run_id=?',(result['id'],))['n']==3
    assert components.store.one('SELECT state FROM memories')['state']=='draft'


async def test_decoy_does_not_solve(components):
    s=components.store
    c=s.create_challenge(ChallengeInput(title='decoy',description='Inspect payload.txt',authorized=True))
    SecureFiles(s.root/'inputs'/c['id']).write('payload.txt',base64.b64encode(b'flag{decoy}'))
    s.execute('INSERT INTO verifiers VALUES(?,?)',(c['id'],digest('flag{actual}')))
    run=s.create_run(c['id'],RunInput(auto_distill=False))
    result=await components.runtime.run(run['id'])
    assert result['state']!='solved'
    assert s.one('SELECT status FROM candidates')['status']=='rejected'


async def test_no_verifier_means_awaiting_verification(components):
    s=components.store;c=s.create_challenge(ChallengeInput(title='candidate',description='Inspect payload.txt',authorized=True))
    SecureFiles(s.root/'inputs'/c['id']).write('payload.txt',base64.b64encode(b'flag{possible}'))
    run=s.create_run(c['id'],RunInput(auto_distill=False))
    result=await components.runtime.run(run['id'])
    assert result['state']=='awaiting_verification'


async def test_cannot_start_same_run_twice(components,run):
    components.store.state(run['id'],'running')
    with pytest.raises(Conflict):await components.runtime.run(run['id'])


async def test_pause_during_model_call_keeps_uncertainty(components,run):
    entered=asyncio.Event()
    class Slow:
        async def complete(self,profile,messages,tools):
            entered.set();await asyncio.sleep(30)
    components.runtime.gateway=ModelGateway(components.store,components.settings,Slow())
    task=components.runtime.launch(run['id'])
    await entered.wait();await components.runtime.pause(run['id'])
    assert components.store.run(run['id'])['state']=='paused'
    assert components.store.one('SELECT status FROM model_calls')['status']=='uncertain'


def test_resume_protocol_repairs_without_reexecution(components,run,task):
    s=components.store
    s.append_message(task['id'],{'role':'assistant','content':'','tool_calls':[{'id':'unknown-call',
        'type':'function','function':{'name':'sandbox_exec','arguments':'{"command":"do-not-repeat"}'}}]})
    components.runtime.repair_interrupted_exchange(task)
    history=s.messages(task['id'])
    assert 'UNKNOWN_AFTER_INTERRUPTION' in history[-1]['content']
    assert s.one('SELECT COUNT(*) AS n FROM executions')['n']==0


def candidate(components):
    return components.evolution.propose(SkillSpec(key='misc-baseline',category='misc',
        applicability='When the input alphabet fits a known encoding',
        instructions=['Inspect the original bytes before trying a transform.']))


def suite():
    return BenchmarkSuite(name='Native integration fixture only',cases=[BenchmarkCase(
        name='Fixture case '+str(i),category='misc',description=f'Fixture {i}: decode payload.txt',
        files_base64={'payload.txt':base64.b64encode(base64.b64encode(f'flag{{fixture_{i}}}'.encode())).decode()},
        expected_sha256=digest(f'flag{{fixture_{i}}}')) for i in range(3)])


async def test_paired_evaluator_executes_both_arms_but_fixture_cannot_promote(components):
    cand=candidate(components)
    result=await components.evaluator.evaluate(cand['id'],suite(),RunInput(auto_distill=False,max_rounds=2))
    assert result['mode']=='fixture' and result['state']=='completed'
    report=json.loads(result['report'])
    assert len(report['cases'])==3 and report['baseline_solved']==report['candidate_solved']==3
    assert not report['eligible']
    assert components.store.one("SELECT COUNT(*) AS n FROM runs WHERE mode='benchmark'")['n']==6
    assert components.store.one('SELECT COUNT(*) AS n FROM memories')['n']==0
    with pytest.raises(Conflict):components.evolution.promote(cand['id'],result['id'])


async def test_duplicate_holdout_rejected(components):
    cand=candidate(components);s=suite()
    s.cases[1]=s.cases[0].model_copy(update={'name':'same content different title'})
    with pytest.raises(ValueError,match='duplicate'):
        await components.evaluator.evaluate(cand['id'],s,RunInput(auto_distill=False))


def test_gate_requires_real_improvement_and_no_regression():
    case=lambda name,b,c,bt=100,ct=80:{'name':name,'baseline':{'solved':b,'tokens':bt,'cost_usd':0.1},
                                   'candidate':{'solved':c,'tokens':ct,'cost_usd':0.1}}
    result=Evaluator.gate([case(str(i),True,True) for i in range(3)])
    assert result['eligible']
    result=Evaluator.gate([case('a',True,False),case('b',False,True),case('c',True,True)])
    assert not result['eligible'] and result['regressions']==1
    result=Evaluator.gate([case(str(i),True,True,100,100) for i in range(3)])
    assert not result['eligible']


def test_gate_rejects_uncertain_accounting():
    cases=[{'name':str(i),'baseline':{'solved':True,'tokens':100,'cost_usd':0.1},
            'candidate':{'solved':True,'tokens':80,'cost_usd':0.1,'uncertain_calls':1}} for i in range(3)]
    assert not Evaluator.gate(cases)['eligible']


def test_strategy_secrets_rejected(components):
    with pytest.raises(ValueError):
        components.evolution.propose(SkillSpec(key='bad-skill',category='misc',
            applicability='Whenever an attachment is provided',instructions=['Always output flag{memorized_answer}']))


def test_candidate_does_not_replace_active_strategy(components):
    before=components.store.one("SELECT id FROM skills WHERE key='misc-baseline' AND state='active'")['id']
    cand=candidate(components)
    assert cand['parent_id']==before and cand['state']=='candidate'
    assert components.store.one("SELECT id FROM skills WHERE key='misc-baseline' AND state='active'")['id']==before


def test_new_candidate_cannot_be_rolled_back_to(components):
    cand=candidate(components)
    with pytest.raises(Conflict):components.evolution.rollback(cand['id'])


async def test_complete_learning_cycle_quarantines_fixture_results(components):
    source=await create_demo(components)
    result=await components.learning.execute(source['id'],suite(),RunInput(auto_distill=False,max_rounds=2),auto_promote=True)
    report=json.loads(result['report'])
    assert result['state']=='completed'
    assert report['promotion_requested'] and not report['promoted']
    assert components.store.one('SELECT state FROM skills WHERE id=?',(report['candidate_id'],))['state']=='candidate'
    assert components.store.one('SELECT state FROM memories WHERE id=?',(report['memory_id'],))['state']=='draft'
    assert components.store.run(source['id'])['state']=='solved'


async def test_learning_requires_terminal_episode(components,run):
    with pytest.raises(Conflict):
        await components.learning.execute(run['id'],suite(),RunInput())


def synthetic_evaluation(components, cand):
    """Unit-test a gate transition with a constructed record, not a measured result."""
    from phoenix.domain import dump, now, uid
    eid = uid('eval')
    report = {'eligible': True, 'candidate_sha256': cand['sha256']}
    components.store.execute('INSERT INTO evaluations VALUES(?,?,?,?,?,?,?,?,?)',
        (eid, cand['id'], cand['parent_id'], 'completed', 'unit-test-only', 'live', dump(report), now(), now()))
    return eid


def test_atomic_promotion_and_rollback_transitions(components):
    cand = candidate(components)
    eid = synthetic_evaluation(components, cand)
    promoted = components.evolution.promote(cand['id'], eid)
    assert promoted['state'] == 'active'
    assert components.store.one('SELECT state FROM skills WHERE id=?', (cand['parent_id'],))['state'] == 'retired'
    components.evolution.rollback(cand['parent_id'])
    assert components.store.one('SELECT state FROM skills WHERE id=?', (cand['id'],))['state'] == 'retired'
    assert components.store.one('SELECT state FROM skills WHERE id=?', (cand['parent_id'],))['state'] == 'active'


def test_candidate_hash_change_invalidates_promotion(components):
    cand = candidate(components)
    eid = synthetic_evaluation(components, cand)
    components.store.execute('UPDATE skills SET sha256=? WHERE id=?', ('changed', cand['id']))
    with pytest.raises(Conflict, match='changed'):
        components.evolution.promote(cand['id'], eid)


def test_baseline_change_requires_new_paired_comparison(components):
    cand = candidate(components)
    eid = synthetic_evaluation(components, cand)
    other = candidate(components)
    other_eval = synthetic_evaluation(components, other)
    components.evolution.promote(other['id'], other_eval)
    with pytest.raises(Conflict, match='Baseline changed'):
        components.evolution.promote(cand['id'], eid)
