import json

import httpx
import pytest

from phoenix.api import create_app
from phoenix.domain import Completion, Plan, RunInput, TaskSpec


@pytest.fixture
def solving_client(components):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(components.settings, components)),
        base_url='http://test', headers={'Authorization': 'Bearer ' + components.settings.web_token})


@pytest.mark.asyncio
async def test_replay_is_paginated_chronological_and_run_scoped(components, run, solving_client):
    for i in range(245):
        components.store.event(run['id'], 'test.entry', {'index': i})
    other = components.store.create_run(run['challenge_id'], RunInput())
    components.store.event(other['id'], 'private.other', {})
    async with solving_client as client:
        all_rows, cursor = [], 0
        while True:
            page = (await client.get(f"/api/runs/{run['id']}/timeline?after={cursor}&limit=80")).json()
            all_rows.extend(page['items'])
            cursor = page['next_after']
            if not page['has_more']:
                break
        assert len(all_rows) == 246
        assert [e['seq'] for e in all_rows] == sorted(set(e['seq'] for e in all_rows))
        assert not any(e['kind'] == 'private.other' for e in all_rows)
        assert all_rows[-1]['payload'] == {'index': 244}
        before = (await client.get(f"/api/runs/{run['id']}/timeline?before={all_rows[2]['seq']}")).json()
        assert len(before['items']) == 2
        assert (await client.get(f"/api/runs/{run['id']}/timeline?limit=500")).status_code == 422
        assert (await client.get('/api/runs/missing/timeline')).status_code == 404
        assert (await client.get(f"/api/runs/{run['id']}/timeline", headers={'Authorization': ''})).status_code == 401


@pytest.mark.asyncio
async def test_event_actor_uses_historical_assignment(components, run, task, solving_client):
    s = components.store
    s.event(run['id'], 'swarm.assigned', {'worker_id': 'old-worker'}, task['id'])
    s.event(run['id'], 'worker.message', {'content': 'first attempt'}, task['id'])
    s.event(run['id'], 'swarm.assigned', {'worker_id': 'new-worker'}, task['id'])
    s.event(run['id'], 'worker.message', {'content': 'second attempt'}, task['id'])
    async with solving_client as client:
        rows = (await client.get(f"/api/runs/{run['id']}/timeline")).json()['items']
    messages = [e for e in rows if e['kind'] == 'worker.message']
    assert [e['worker_id'] for e in messages] == ['old-worker', 'new-worker']


@pytest.mark.asyncio
async def test_operator_message_persists_and_reaches_planner(components, run, solving_client, monkeypatch):
    async with solving_client as client:
        response = await client.post(f"/api/runs/{run['id']}/messages", json={'content': '  Compare the two branches  '})
        assert response.status_code == 201
        assert response.json()['delivery'] == 'next_context'
        assert (await client.post(f"/api/runs/{run['id']}/messages", json={'content': ' \n '})).status_code == 422
    captured = []

    async def complete(rid, role, messages, tools=None, *, profile_override=None, worker_id=None, task_id=None):
        captured.extend(messages)
        return Completion(text=json.dumps({'rationale': 'No additional tasks', 'stop': True, 'tasks': []}))

    monkeypatch.setattr(components.gateway, 'complete', complete)
    await components.runtime.plan(run['id'], 'operator message')
    core = json.loads(captured[1]['content'])
    assert core['operator_messages'][0]['content'] == 'Compare the two branches'
    # Reopening the store preserves the operator conversation.
    from phoenix.store import Store
    reopened = Store(components.store.root)
    assert reopened.all("SELECT * FROM events WHERE run_id=? AND kind='operator.message'", (run['id'],))


@pytest.mark.asyncio
async def test_terminal_round_rejects_undeliverable_message(components, run, solving_client):
    components.store.state(run['id'], 'exhausted')
    async with solving_client as client:
        assert (await client.post(f"/api/runs/{run['id']}/messages", json={'content': 'Continue'})).status_code == 409


@pytest.mark.asyncio
async def test_continue_creates_new_round_with_explicit_handoff(components, run, solving_client, monkeypatch):
    s = components.store
    s.add_plan(run['id'], Plan(rationale='First attempt', tasks=[TaskSpec(key='attempt', goal='Inspect data')]))
    s.state(run['id'], 'exhausted', 'First branch exhausted')
    launched = []
    monkeypatch.setattr(components.runtime, 'launch', launched.append)
    async with solving_client as client:
        response = await client.post(f"/api/runs/{run['id']}/continue", json={'content': 'Try a different branch'})
        assert response.status_code == 201
        new = response.json()
        assert new['id'] != run['id'] and new['challenge_id'] == run['challenge_id']
        assert new['billed_tokens'] == 0 and new['config'] == run['config']
        assert launched == [new['id']]
        core = components.runtime.core(new['id'])
        assert core['previous_round']['run_id'] == run['id']
        assert core['previous_round']['summaries_are_unverified_reference_data']
        assert core['operator_messages'][0]['content'] == 'Try a different branch'
        assert s.run(run['id'])['state'] == 'exhausted'
        assert (await client.post(f"/api/runs/{new['id']}/continue", json={'content': 'duplicate'})).status_code == 409


@pytest.mark.asyncio
async def test_demo_cannot_silently_start_paid_continuation(components, run, solving_client):
    components.store.execute("UPDATE runs SET state='solved',mode='demo' WHERE id=?", (run['id'],))
    async with solving_client as client:
        assert (await client.post(f"/api/runs/{run['id']}/continue", json={'content': 'Continue'})).status_code == 409


@pytest.mark.asyncio
async def test_workspace_preview_is_bounded_and_rejects_traversal(components, run, task, solving_client, tmp_path):
    fs = components.tools.workspace(run['id'])
    fs.write('branch/result.txt', b'a' * 32000 + b'end')
    outside = tmp_path / 'outside.txt'
    outside.write_text('secret')
    (fs.root / 'link.txt').symlink_to(outside)
    async with solving_client as client:
        base = f"/api/runs/{run['id']}/workspace"
        listing = (await client.get(base)).json()
        assert [e['path'] for e in listing['artifacts']] == ['branch/result.txt']
        page = (await client.get(base + '/read?path=branch/result.txt')).json()
        assert len(page['content']) == 32000 and page['next_offset'] == 32000
        assert (await client.get(base + '/read?path=branch/result.txt&offset=32000')).json()['content'] == 'end'
        assert (await client.get(base + '/read?path=../outside.txt')).status_code == 422
        assert (await client.get(base + '/read?path=C:/outside.txt')).status_code == 422
        assert (await client.get(base + '/read?path=result.txt&area=host')).status_code == 422
        assert (await client.get(base + '/read?path=link.txt')).status_code == 422
        assert (await client.get(base + '/read?path=missing.txt')).status_code == 404


@pytest.mark.asyncio
async def test_worker_public_message_is_in_durable_timeline(components, run, task, monkeypatch):
    from phoenix.domain import ToolCall
    e = components.evidence.record(run['id'], task['id'], 'fixture', {}, 'real fixture evidence')

    async def complete(*args, **kwargs):
        return Completion(text='I inspected the original observation.', calls=[ToolCall(id='finish', name='task_finish',
            arguments={'summary': 'Original evidence inspected', 'evidence_ids': [e['id']], 'outcome': 'done'})])

    monkeypatch.setattr(components.gateway, 'complete', complete)
    await components.runtime.worker(run['id'], task)
    rows = components.store.all("SELECT payload FROM events WHERE run_id=? AND kind='worker.message'", (run['id'],))
    assert json.loads(rows[0]['payload'])['content'] == 'I inspected the original observation.'
    completed = components.store.one("SELECT payload FROM events WHERE run_id=? AND kind='tool.completed'", (run['id'],))
    assert json.loads(completed['payload'])['call_id'] == 'finish'


@pytest.mark.asyncio
async def test_graph_handoff_requires_a_real_evidence_read(components, solving_client):
    from phoenix.swarm_demo import create_swarm_demo
    result = await create_swarm_demo(components)
    async with solving_client as client:
        detail = (await client.get(f"/api/runs/{result['id']}")).json()
    assert len(detail['evidence_handoffs']) == 1
    handoff = detail['evidence_handoffs'][0]
    assert handoff['source_task_id'] != handoff['target_task_id']
    by_id = {t['id']: t for t in detail['tasks']}
    assert by_id[handoff['target_task_id']]['key'] == 'review'
    assert handoff['evidence_id'] in {e['id'] for e in detail['evidence']}


@pytest.mark.asyncio
async def test_phoenix_usage_contract_uses_native_calls_without_fake_zero_prices(components, solving_client):
    from phoenix.swarm_demo import create_swarm_demo
    result = await create_swarm_demo(components)
    rid = result['id']
    async with solving_client as client:
        detail = (await client.get(f'/api/runs/{rid}')).json()
        response = await client.get('/api/usage', params={'run_id': rid})
        assert response.status_code == 200
        usage = response.json()
        assert usage['totals']['records'] == len(detail['model_calls'])
        assert usage['totals']['total_tokens'] == sum(c['input_tokens'] + c['output_tokens'] for c in detail['model_calls'])
        assert usage['totals']['cost'] is None
        assert usage['totals']['unpriced'] == len(detail['model_calls'])
        assert 'coordinator' in {row['name'] for row in usage['groups']['worker_id']}
        assert all(c['created'] is not None and c['ended'] is not None for c in detail['model_calls'])
        assert any(c['worker_id'] for c in detail['model_calls'])
        assert (await client.get('/api/usage?run_id=missing')).status_code == 404
        assert (await client.get('/api/usage?run_id='+rid, headers={'Authorization': ''})).status_code == 401
