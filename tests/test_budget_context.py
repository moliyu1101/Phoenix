import concurrent.futures

import pytest

from phoenix.budget import Ledger, upper_token_estimate
from phoenix.config import ModelProfile
from phoenix.context import ContextCompiler
from phoenix.domain import BudgetExceeded, ContextExceeded, dump


def test_settle_budget(components, run, task):
    l = Ledger(components.store)
    p = ModelProfile(model='fixture', output_tokens=256, input_usd_per_million=1, output_usd_per_million=2)
    cid = l.reserve(run['id'], 'solver', p, 500)
    assert components.store.run(run['id'])['held_tokens'] == 756
    l.settle(cid, 100, 50)
    row = components.store.run(run['id'])
    assert row['held_tokens'] == 0 and row['billed_tokens'] == 150
    assert row['billed_usd'] == pytest.approx(0.0002)
    l.settle(cid, 100, 50)
    assert components.store.run(run['id'])['billed_tokens'] == 150


def test_unknown_usage_keeps_reservation(components, run, task):
    l = Ledger(components.store)
    cid = l.reserve(run['id'], 'solver', ModelProfile(output_tokens=256), 500)
    l.settle(cid, None, None)
    row = components.store.run(run['id'])
    assert row['held_tokens'] == 756
    assert components.store.one('SELECT status FROM model_calls WHERE id=?',(cid,))['status'] == 'uncertain'


def test_uncertain_model_call_not_refunded(components, run, task):
    l = Ledger(components.store)
    cid = l.reserve(run['id'], 'solver', ModelProfile(output_tokens=256), 500)
    l.uncertain(cid)
    assert components.store.run(run['id'])['held_tokens'] == 756


def test_atomic_concurrent_budget(components, run, task):
    s = components.store
    cfg = run['config']; cfg['budget']['max_tokens'] = 1000
    s.execute('UPDATE runs SET config=? WHERE id=?', (dump(cfg),run['id']))
    l = Ledger(s)
    def reserve(_):
        try:
            return l.reserve(run['id'],'solver',ModelProfile(output_tokens=256),400)
        except BudgetExceeded:
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(reserve, range(8)))
    assert sum(r is not None for r in rows) == 1


def test_usd_cap_requires_known_prices(components, run, task):
    cfg=run['config'];cfg['budget']['max_usd']=1
    components.store.execute('UPDATE runs SET config=? WHERE id=?',(dump(cfg),run['id']))
    with pytest.raises(BudgetExceeded, match='prices'):
        Ledger(components.store).reserve(run['id'],'solver',ModelProfile(),100)


def test_excess_actual_usage_stops_next_call(components, run, task):
    cfg=run['config'];cfg['budget']['max_tokens']=1000
    components.store.execute('UPDATE runs SET config=? WHERE id=?',(dump(cfg),run['id']))
    l=Ledger(components.store);p=ModelProfile(output_tokens=256)
    cid=l.reserve(run['id'],'solver',p,100);l.settle(cid,1200,50)
    with pytest.raises(BudgetExceeded):l.reserve(run['id'],'solver',p,10)


def test_core_is_never_silently_truncated():
    with pytest.raises(ContextExceeded):
        ContextCompiler().compile('x'*5000,{},[],[],2000,256,[])


def test_tool_schema_counted():
    assert upper_token_estimate([], [{'schema':'x'*1000}]) > upper_token_estimate([]) + 900


def test_complete_tool_groups_only():
    history=[]
    for i in range(5):
        history += [{'role':'assistant','content':'x'*600,'tool_calls':[{'id':str(i)}]},
                    {'role':'tool','tool_call_id':str(i),'content':'y'*600}]
    result,stats=ContextCompiler().compile('policy',{'task':'must stay'},history,[],4500,256,[])
    requested={c['id'] for m in result for c in m.get('tool_calls',[])}
    answered={m['tool_call_id'] for m in result if m['role']=='tool'}
    assert requested==answered and stats['omitted_messages']>0
    assert result[0]['content']=='policy'


def test_incomplete_tool_group_rejected():
    with pytest.raises(ContextExceeded):
        ContextCompiler().compile('p',{},[{'role':'assistant','tool_calls':[{'id':'a'}],'content':''}],[],4000,256,[])


def test_reference_data_budgeted():
    result,stats=ContextCompiler().compile('p',{'task':'fixed'},[],[],1500,256,[{'id':'large','body':'x'*5000}])
    assert not stats['retrieved_ids']
    assert 'fixed' in str(result)
