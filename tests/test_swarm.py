import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from phoenix.api import create_app
from phoenix.config import ModelProfile, Settings, WorkerProfile
from phoenix.domain import BudgetSpec, ChallengeInput, Conflict, Plan, RunInput, TaskSpec, dump
from phoenix.service import Components
from phoenix.swarm_demo import SwarmDemonstrationProvider, create_swarm_demo


def plan_two(s, rid, role='solver'):
    s.add_plan(rid, Plan(rationale='Independent experiments', tasks=[
        TaskSpec(key='left', goal='Inspect the left attachment independently', role=role),
        TaskSpec(key='right', goal='Inspect the right attachment independently', role=role),
    ]))
    s.state(rid, 'running')


def test_unique_worker_ids(tmp_path):
    worker = WorkerProfile(id='one', name='One', roles=['solver'])
    with pytest.raises(ValidationError, match='unique'):
        Settings(data_dir=tmp_path, workers=[worker, worker])


def test_unknown_worker_profile(tmp_path):
    with pytest.raises(ValidationError, match='Unknown worker model'):
        Settings(data_dir=tmp_path, workers=[WorkerProfile(id='one', name='One', roles=['solver'], profile='missing')])


def test_worker_selection_and_category(components, run):
    swarm = components.runtime.swarm
    with pytest.raises(ValueError, match='Unknown worker IDs'):
        swarm.selected({'worker_ids': ['missing']}, 'misc')
    with pytest.raises(ValueError, match='Duplicate'):
        swarm.selected({'worker_ids': ['scout', 'scout']}, 'misc')
    assert [w.id for w in swarm.selected({'worker_ids': ['reviewer']}, 'misc')] == ['reviewer']
    components.settings.workers = [WorkerProfile(id='web-only', name='Web', roles=['solver'], categories=['web'])]
    with pytest.raises(ValueError, match='No enabled'):
        swarm.selected({}, 'crypto')


def test_roster_is_snapshotted_and_reloaded(components, run):
    swarm = components.runtime.swarm
    swarm.ensure(run['id'])
    first = swarm.roster(run['id'])
    components.settings.profiles['default'].model = 'changed-model'
    swarm.ensure(run['id'])
    assert swarm.roster(run['id']) == first
    assert len(first) == 4


def test_atomic_named_claims_no_duplicate_active_worker(components, run):
    s, sw = components.store, components.runtime.swarm
    sw.ensure(run['id'])
    plan_two(s, run['id'])
    left, right = sw.claim(run['id'], 'engine'), sw.claim(run['id'], 'engine')
    assert left['id'] != right['id']
    assert left['_worker']['id'] != right['_worker']['id']
    assert sw.claim(run['id'], 'engine') is None
    description = sw.describe(run['id'])
    assert description['live_workers'] == 2
    assert {t['worker_id'] for t in description['tasks']} == {'solver-a', 'solver-b'}


def test_worker_role_routing(components, run):
    s, sw = components.store, components.runtime.swarm
    sw.ensure(run['id'])
    plan_two(s, run['id'], role='reviewer')
    task = sw.claim(run['id'], 'engine')
    assert task['_worker']['id'] == 'reviewer'
    assert sw.claim(run['id'], 'engine') is None


def test_drain_does_not_kill_inflight_task(components, run):
    s, sw = components.store, components.runtime.swarm
    sw.ensure(run['id'])
    plan_two(s, run['id'])
    task = sw.claim(run['id'], 'engine')
    sw.enabled(run['id'], task['_worker']['id'], False)
    worker = next(w for w in sw.describe(run['id'])['workers'] if w['id'] == task['_worker']['id'])
    assert worker['status'] == 'draining'
    assert s.one('SELECT state FROM tasks WHERE id=?', (task['id'],))['state'] == 'running'


def test_swarm_scale_and_terminal_guard(components, run):
    sw, s = components.runtime.swarm, components.store
    sw.ensure(run['id'])
    assert sw.concurrency(run['id'], 1)['concurrency'] == 1
    with pytest.raises(ValueError):
        sw.concurrency(run['id'], 17)
    s.state(run['id'], 'exhausted')
    with pytest.raises(Conflict):
        sw.concurrency(run['id'], 4)
    with pytest.raises(Conflict):
        sw.enabled(run['id'], 'solver-a', False)


def test_dynamic_add_model_profile_and_duplicate(components, run):
    sw, s = components.runtime.swarm, components.store
    sw.ensure(run['id'])
    components.settings.profiles['specialist'] = ModelProfile(model='specialist-model')
    spec = WorkerProfile(id='new-specialist', name='Specialist', roles=['solver'], profile='specialist')
    sw.add(run['id'], spec)
    assert sw.roster(run['id'])[-1]['profiles']['solver']['model'] == 'specialist-model'
    with pytest.raises(Conflict, match='already'):
        sw.add(run['id'], spec)
    with pytest.raises(ValueError, match='Unknown model'):
        sw.add(run['id'], WorkerProfile(id='bad', name='Bad', roles=['solver'], profile='missing'))


def test_no_eligible_worker_blocks_without_spinning(components, run):
    sw, s = components.runtime.swarm, components.store
    sw.ensure(run['id'])
    plan_two(s, run['id'])
    sw.enabled(run['id'], 'solver-a', False)
    sw.enabled(run['id'], 'solver-b', False)
    sw.block_unserviceable(run['id'])
    assert all(t['state'] == 'blocked' for t in s.tasks(run['id']))


def test_interrupted_transcript_keeps_worker_affinity(components, run):
    sw, s = components.runtime.swarm, components.store
    sw.ensure(run['id'])
    plan_two(s, run['id'])
    task = sw.claim(run['id'], 'engine')
    s.finish(task['id'], 'engine', 'interrupted', 'Network side effect unknown')
    s.execute("UPDATE tasks SET state='pending' WHERE id=?", (task['id'],))
    # Another worker may claim other work, but cannot inherit this raw model transcript.
    other = s.claim(run['id'], 'engine-2', roles=['solver'], worker_id='solver-b')
    assert other['id'] != task['id']
    resumed = sw.claim(run['id'], 'engine-2')
    assert resumed['id'] == task['id']
    assert resumed['_worker']['id'] == task['_worker']['id']


def test_disabled_interrupted_owner_blocks_for_replanning(components, run):
    sw, s = components.runtime.swarm, components.store
    sw.ensure(run['id'])
    plan_two(s, run['id'])
    task = sw.claim(run['id'], 'engine')
    s.finish(task['id'], 'engine', 'interrupted', 'Stopped')
    s.execute("UPDATE tasks SET state='pending' WHERE id=?", (task['id'],))
    sw.enabled(run['id'], task['_worker']['id'], False)
    sw.block_unserviceable(run['id'])
    assert s.one('SELECT state FROM tasks WHERE id=?', (task['id'],))['state'] == 'blocked'


@pytest.mark.asyncio
async def test_parallel_handoff_real_tools_and_provenance(components):
    result = await create_swarm_demo(components)
    s = components.store
    assert result['state'] == 'solved' and result['mode'] == 'demo'
    tasks = {t['key']: t for t in s.tasks(result['id'])}
    assert all(t['state'] == 'done' for t in tasks.values())
    assert tasks['inspect']['started'] < tasks['decode']['ended']
    assert tasks['decode']['started'] < tasks['inspect']['ended']
    assert tasks['review']['started'] >= max(tasks['inspect']['ended'], tasks['decode']['ended'])
    event = s.one("SELECT payload FROM events WHERE run_id=? AND kind='swarm.demo_result'", (result['id'],))
    values = json.loads(event['payload'])
    assert values['peak_concurrent_worker_requests'] == 2
    assert values['reviewer_saw_shared_facts'] is True
    assert len(s.all('SELECT id FROM facts WHERE run_id=?', (result['id'],))) == 2
    assert len(s.all('SELECT * FROM swarm_calls WHERE run_id=?', (result['id'],))) >= 9
    assert not s.all('SELECT id FROM evidence WHERE run_id=? AND ok=0', (result['id'],))


@pytest.mark.asyncio
async def test_different_worker_models_actually_reach_provider(tmp_path):
    provider = SwarmDemonstrationProvider()
    settings = Settings(data_dir=tmp_path, profiles={
        'default': ModelProfile(model='control'), 'left': ModelProfile(model='model-left'),
        'right': ModelProfile(model='model-right'),
    }, workers=[WorkerProfile(id='analyst', name='A', roles=['analyst'], profile='left'),
                WorkerProfile(id='solver', name='S', roles=['solver'], profile='right'),
                WorkerProfile(id='reviewer', name='R', roles=['reviewer'])])
    c = Components(settings, provider)
    challenge = c.store.create_challenge(ChallengeInput(title='Parallel fixture', description='Read the attachments', authorized=True))
    from phoenix.filesystem import SecureFiles
    import base64
    fs = SecureFiles(c.store.root / 'inputs' / challenge['id'])
    fs.write('payload.txt', base64.b64encode(b'fixture-data'))
    fs.write('metadata.txt', b'fixture-metadata')
    run = c.store.create_run(challenge['id'], RunInput(auto_distill=False, max_rounds=2, budget=BudgetSpec(max_tokens=500000)))
    result = await c.runtime.run(run['id'])
    assert result['state'] == 'exhausted'
    assert {'model-left', 'model-right', 'control'} <= provider.models
    calls = c.store.all('''SELECT m.profile,s.worker_id FROM model_calls m
                         JOIN swarm_calls s ON m.id=s.call_id WHERE m.run_id=?''', (run['id'],))
    assert {json.loads(row['profile'])['model'] for row in calls if row['worker_id'] == 'analyst'} == {'model-left'}
    assert {json.loads(row['profile'])['model'] for row in calls if row['worker_id'] == 'solver'} == {'model-right'}


@pytest.mark.asyncio
async def test_concurrency_one_serializes_workers(tmp_path):
    provider = SwarmDemonstrationProvider()
    c = Components(Settings(data_dir=tmp_path, profiles={'default': ModelProfile(model='fixture')}), provider)
    challenge = c.store.create_challenge(ChallengeInput(title='Serial fixture', description='Read original inputs', authorized=True))
    from phoenix.filesystem import SecureFiles
    import base64
    fs = SecureFiles(c.store.root / 'inputs' / challenge['id'])
    fs.write('payload.txt', base64.b64encode(b'plain data'))
    fs.write('metadata.txt', b'plain metadata')
    run = c.store.create_run(challenge['id'], RunInput(concurrency=1, auto_distill=False, max_rounds=2,
                                                      budget=BudgetSpec(max_tokens=500000)))
    await c.runtime.run(run['id'])
    assert provider.peak_workers == 1
    assert all(t['state'] == 'done' for t in c.store.tasks(run['id']))


@pytest.mark.asyncio
async def test_workbench_auth_swarm_and_metadata_routes(components, run):
    sw = components.runtime.swarm
    sw.ensure(run['id'])
    transport = httpx.ASGITransport(app=create_app(components.settings, components))
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        assert (await client.get('/api/swarm/catalog')).status_code == 401
        client.headers['Authorization'] = 'Bearer ' + components.settings.web_token
        assert (await client.get('/api/swarm/catalog')).status_code == 200
        roster = (await client.get(f"/api/runs/{run['id']}/swarm")).json()
        assert len(roster['workers']) == 4
        assert 'test-secret-token' not in json.dumps(roster)
        response = await client.patch(f"/api/runs/{run['id']}/swarm", json={'concurrency': 3})
        assert response.json()['concurrency'] == 3
        folder = (await client.post('/api/workbench/folders', json={'name': 'Crypto'})).json()
        assert (await client.patch(f"/api/workbench/runs/{run['id']}", json={
            'name': 'Pinned run', 'pinned': True, 'folder_id': folder['id']})).status_code == 200
        row = (await client.get('/api/workbench/runs')).json()[0]
        assert row['name'] == 'Pinned run' and row['pinned']
        assert (await client.delete(f"/api/workbench/runs/{run['id']}")).status_code == 409
        components.store.state(run['id'], 'exhausted')
        assert (await client.delete(f"/api/workbench/runs/{run['id']}")).status_code == 200
        assert (await client.get('/api/workbench/runs')).json() == []
        assert components.store.run(run['id'])['id'] == run['id']
        assert (await client.get('/api/agent-runtimes/descriptors')).json()['schema_version'] == 1
        assert (await client.get(f"/api/runs/{run['id']}/graph/export?format=jsonl")).status_code == 200
        assert (await client.get(f"/api/runs/{run['id']}/graph/export?format=sqlite")).status_code == 422


@pytest.mark.asyncio
async def test_api_swarm_demo(components):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(components.settings, components)),
                                base_url='http://test', headers={'Authorization': 'Bearer ' + components.settings.web_token}) as client:
        response = await client.post('/api/swarm-demo')
        assert response.status_code == 200
        assert response.json()['state'] == 'solved'


def test_env_value_precedence(monkeypatch):
    from phoenix.config import env_value
    monkeypatch.delenv('PHOENIX_MODEL', raising=False)
    assert env_value('PHOENIX_MODEL', 'fallback') == 'fallback'
    monkeypatch.setenv('PHOENIX_MODEL', 'configured-model')
    assert env_value('PHOENIX_MODEL') == 'configured-model'
    monkeypatch.setenv('PHOENIX_MODEL', '')
    assert env_value('PHOENIX_MODEL') == ''
