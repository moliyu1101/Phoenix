import asyncio
import base64

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from phoenix.competition import Competitions, competition_loop
from phoenix.competition_api import attach_competition
from phoenix.domain import Conflict, NotFound, digest
from phoenix.filesystem import SecureFiles
from phoenix.vendor.engine.platform.contracts.modules import ArtifactObject, SubmissionResult, SyncResult


def snapshot(key, name, category='misc', points=100, hidden=False):
    return {'external_challenge_id': key, 'name': name, 'category': category, 'points': points,
            'hidden': hidden, 'remote_state': 'open', 'description': name, 'artifacts': []}


class FakeAdapter:
    def __init__(self, snapshots, status='correct'):
        self.snapshots, self.status, self.submissions = snapshots, status, []

    async def sync_competition(self, request):
        visible = [s for s in self.snapshots if not s.get('hidden')]
        return SyncResult(connection_id=request.connection_id, synced_challenges=len(visible),
                          detail={'external_competition_id': 'game-1', 'snapshots': self.snapshots})

    async def fetch_artifact(self, ref):
        return ArtifactObject(sha256='0' * 64, media_type='text/plain', content=b'fixture')

    async def submit(self, request):
        self.submissions.append(request)
        return SubmissionResult(submission_id=f'sub-{len(self.submissions)}', status=self.status)

    async def aclose(self):
        pass


async def connect(c, snapshots, status='correct'):
    result = await c.platforms.configure('ctfd', 'http://platform.test', 'fixture-secret')
    cid = result['id']
    adapter = FakeAdapter(snapshots, status)
    c.platforms.adapters[cid] = adapter
    return cid, adapter


@pytest.fixture
def scheduler(components):
    service = Competitions(components)
    components.competitions = service
    return service


@pytest.fixture
def no_launch(components, monkeypatch):
    launched = []
    monkeypatch.setattr(components.runtime, 'launch', lambda rid: launched.append(rid))
    return launched


async def test_register_sync_builds_queue(components, scheduler):
    cid, _ = await connect(components, [snapshot('7', 'Web One', 'web', 200),
                                        snapshot('8', 'Rev Two', 'rev', 150),
                                        snapshot('9', 'Locked', 'misc', 50, hidden=True)])
    comp = scheduler.register(cid, '春季赛', 'game-1')
    assert comp['scheduler_state'] == 'paused' and comp['policy']['max_concurrency'] == 2
    result = await scheduler.sync(comp['id'])
    assert result['added'] == 2 and result['visible'] == 3
    queue = scheduler.queue(comp['id'])
    assert {e['challenge_key'] for e in queue} == {'7', '8'}
    assert {e['category'] for e in queue} == {'web', 'reverse'}
    assert all(e['state'] == 'pending' for e in queue)
    again = await scheduler.sync(comp['id'])
    assert again['added'] == 0 and again['updated'] == 2
    with pytest.raises(Conflict):
        scheduler.register(cid, '重复', 'game-1')
    with pytest.raises(ValueError):
        scheduler.register('platform_missing', '未知连接')
    with pytest.raises(NotFound):
        scheduler.describe('comp_missing')


async def test_tick_spawns_run_and_binds(components, scheduler, no_launch):
    cid, _ = await connect(components, [snapshot('7', 'Web One', 'web')])
    comp = scheduler.register(cid, '春季赛')
    await scheduler.sync(comp['id'])
    scheduler.scheduler(comp['id'], 'start')
    result = await scheduler.tick(comp['id'])
    entry = scheduler.queue(comp['id'])[0]
    assert result['admitted'] == [entry['id']]
    assert entry['state'] == 'running' and entry['run_id'] in no_launch
    assert entry['challenge_id'] and entry['admission_decision']['action'] == 'admit'
    run = components.store.run(entry['run_id'])
    assert run['challenge_id'] == entry['challenge_id']
    assert components.store.all('SELECT * FROM platform_links WHERE challenge_id=?', (entry['challenge_id'],))
    assert components.store.all("SELECT * FROM events WHERE run_id=? AND kind='competition.admitted'", (run['id'],))


async def test_policy_admission_respects_concurrency(components, scheduler, no_launch):
    cid, _ = await connect(components, [snapshot('7', 'A', 'misc', 300), snapshot('8', 'B', 'misc', 200),
                                        snapshot('9', 'C', 'misc', 100)])
    comp = scheduler.register(cid, '并发赛', policy={'max_concurrency': 1})
    await scheduler.sync(comp['id'])
    scheduler.scheduler(comp['id'], 'start')
    await scheduler.tick(comp['id'])
    queue = scheduler.queue(comp['id'])
    running = [e for e in queue if e['state'] == 'running']
    assert len(running) == 1 and running[0]['challenge_key'] == '7'
    assert len(no_launch) == 1
    components.store.state(running[0]['run_id'], 'exhausted', 'fixture terminal')
    result = await scheduler.tick(comp['id'])
    assert result['settled'] == [running[0]['id']] and len(result['admitted']) == 1
    queue = scheduler.queue(comp['id'])
    assert [e['state'] for e in queue].count('running') == 1
    assert next(e for e in queue if e['challenge_key'] == '7')['state'] == 'exhausted'
    assert len(no_launch) == 2


async def test_category_filter_holds_entry(components, scheduler, no_launch):
    cid, _ = await connect(components, [snapshot('7', 'Web', 'web'), snapshot('8', 'Misc', 'misc')])
    comp = scheduler.register(cid, '分类赛', policy={'categories': ['web'], 'max_concurrency': 4})
    await scheduler.sync(comp['id'])
    scheduler.scheduler(comp['id'], 'start')
    await scheduler.tick(comp['id'])
    queue = {e['challenge_key']: e for e in scheduler.queue(comp['id'])}
    assert queue['7']['state'] == 'running'
    assert queue['8']['state'] == 'pending'
    assert queue['8']['admission_decision'] == {'action': 'hold', 'reason': 'category_filtered'}


async def test_tick_survives_bad_entry(components, scheduler, no_launch, monkeypatch):
    cid, _ = await connect(components, [snapshot('bad', 'Broken', 'misc', 500), snapshot('7', 'Good', 'misc', 100)])
    comp = scheduler.register(cid, '容错赛', policy={'max_concurrency': 4})
    await scheduler.sync(comp['id'])
    original = components.platforms.import_challenge

    async def flaky(connection_id, key, *args, **kwargs):
        if key == 'bad':
            raise ValueError('fixture import failure')
        return await original(connection_id, key, *args, **kwargs)

    monkeypatch.setattr(components.platforms, 'import_challenge', flaky)
    scheduler.scheduler(comp['id'], 'start')
    result = await scheduler.tick(comp['id'])
    assert len(result['errors']) == 1 and len(result['admitted']) == 1
    queue = {e['challenge_key']: e for e in scheduler.queue(comp['id'])}
    assert queue['bad']['state'] == 'failed' and 'fixture import failure' in queue['bad']['last_error']
    assert queue['7']['state'] == 'running'


async def test_manual_admit_skip_requeue_and_priority(components, scheduler, no_launch):
    cid, _ = await connect(components, [snapshot('7', 'A'), snapshot('8', 'B')])
    comp = scheduler.register(cid, '手动赛', policy={'max_concurrency': 1})
    await scheduler.sync(comp['id'])
    queue = {e['challenge_key']: e for e in scheduler.queue(comp['id'])}
    scheduler.set_priority(comp['id'], queue['8']['id'], 90)
    assert scheduler.queue(comp['id'])[0]['challenge_key'] == '8'
    scheduler.skip(comp['id'], queue['7']['id'])
    assert next(e for e in scheduler.queue(comp['id']) if e['challenge_key'] == '7')['state'] == 'skipped'
    scheduler.requeue(comp['id'], queue['7']['id'])
    assert next(e for e in scheduler.queue(comp['id']) if e['challenge_key'] == '7')['state'] == 'pending'
    admitted = await scheduler.admit(comp['id'], queue['7']['id'])
    assert admitted['state'] == 'running' and admitted['run_id'] in no_launch
    with pytest.raises(Conflict):
        await scheduler.admit(comp['id'], queue['7']['id'])
    with pytest.raises(Conflict):
        scheduler.skip(comp['id'], queue['7']['id'])


async def test_scheduler_transitions(components, scheduler):
    cid, _ = await connect(components, [snapshot('7', 'A')])
    comp = scheduler.register(cid, '状态赛')
    assert scheduler.scheduler(comp['id'], 'start')['scheduler_state'] == 'running'
    with pytest.raises(Conflict):
        scheduler.scheduler(comp['id'], 'start')
    assert scheduler.scheduler(comp['id'], 'pause')['scheduler_state'] == 'paused'
    with pytest.raises(Conflict):
        scheduler.scheduler(comp['id'], 'pause')
    assert scheduler.scheduler(comp['id'], 'resume')['scheduler_state'] == 'running'
    with pytest.raises(ValueError):
        scheduler.scheduler(comp['id'], 'bogus')


async def test_terminal_reconcile_and_auto_submit_gating(components, scheduler):
    flag = 'flag{competition_native}'
    cid, adapter = await connect(components, [snapshot('7', 'Decode', 'misc')])
    comp = scheduler.register(cid, '回传赛', policy={'auto_submit': False})
    await scheduler.sync(comp['id'])
    challenge = await components.platforms.import_challenge(cid, '7', [])
    SecureFiles(components.store.root / 'inputs' / challenge['id']).write(
        'payload.txt', base64.b64encode(flag.encode()))
    components.store.execute('INSERT INTO verifiers VALUES(?,?)', (challenge['id'], digest(flag)))
    scheduler.scheduler(comp['id'], 'start')
    await scheduler.tick(comp['id'])
    entry = scheduler.queue(comp['id'])[0]
    assert entry['challenge_id'] == challenge['id'] and entry['state'] == 'running'
    await asyncio.wait_for(components.runtime.background[entry['run_id']], 30)
    assert components.store.run(entry['run_id'])['state'] == 'solved'
    result = await scheduler.tick(comp['id'])
    assert result['settled'] == [entry['id']] and not result['submitted']
    assert scheduler.queue(comp['id'])[0]['state'] == 'solved'
    assert not adapter.submissions
    scheduler.set_policy(comp['id'], {**comp['policy'], 'auto_submit': True})
    result = await scheduler.tick(comp['id'])
    assert result['submitted'] == [entry['id']] and len(adapter.submissions) == 1
    settled = scheduler.queue(comp['id'])[0]
    assert settled['submission_id'] and settled['submission_state'] == 'correct'
    assert components.store.one('SELECT status FROM candidates WHERE run_id=?',
                                (entry['run_id'],))['status'] == 'accepted'
    await scheduler.tick(comp['id'])
    assert len(adapter.submissions) == 1
    await components.platforms.shutdown()


async def test_auto_submit_skips_without_accepted_candidate(components, scheduler, no_launch):
    cid, adapter = await connect(components, [snapshot('7', 'A')])
    comp = scheduler.register(cid, '无答案赛', policy={'auto_submit': True})
    await scheduler.sync(comp['id'])
    scheduler.scheduler(comp['id'], 'start')
    await scheduler.tick(comp['id'])
    entry = scheduler.queue(comp['id'])[0]
    components.store.state(entry['run_id'], 'exhausted', 'no candidate')
    result = await scheduler.tick(comp['id'])
    assert result['settled'] == [entry['id']] and not result['submitted']
    assert not adapter.submissions


async def test_background_loop_ticks_running_only(components, scheduler, no_launch):
    cid, _ = await connect(components, [snapshot('7', 'A')])
    running = scheduler.register(cid, '运行赛')
    paused = scheduler.register(cid, '暂停赛', 'game-2')
    await scheduler.sync(running['id'])
    await scheduler.sync(paused['id'])
    scheduler.scheduler(running['id'], 'start')
    stop = asyncio.Event()
    task = asyncio.create_task(competition_loop(components, stop, interval=0.05))
    for _ in range(100):
        if any(e['state'] == 'running' for e in scheduler.queue(running['id'])):
            break
        await asyncio.sleep(0.02)
    stop.set()
    await asyncio.wait_for(task, 5)
    assert any(e['state'] == 'running' for e in scheduler.queue(running['id']))
    assert all(e['state'] == 'pending' for e in scheduler.queue(paused['id']))


async def test_native_rest_contract(components, scheduler, no_launch):
    cid, _ = await connect(components, [snapshot('7', 'Web One', 'web')])
    app = FastAPI()
    attach_competition(app, components)

    @app.exception_handler(NotFound)
    async def not_found(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def bad_request(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=422)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/competitions')).json() == []
        created = await client.post('/api/competitions', json={'connection_id': cid, 'title': '接口赛',
                                                               'external_competition_id': 'game-1'})
        assert created.status_code == 200
        comp = created.json()
        assert (await client.post(f"/api/competitions/{comp['id']}/sync")).json()['added'] == 1
        assert (await client.post(f"/api/competitions/{comp['id']}/scheduler",
                                  json={'action': 'start'})).json()['scheduler_state'] == 'running'
        queue = (await client.get(f"/api/competitions/{comp['id']}/queue")).json()
        assert len(queue) == 1
        entry_id = queue[0]['id']
        assert (await client.patch(f"/api/competitions/{comp['id']}/queue/{entry_id}",
                                   json={'priority': 80})).json()['priority'] == 80
        assert (await client.post(f"/api/competitions/{comp['id']}/queue/{entry_id}/skip")).json()['state'] == 'skipped'
        assert (await client.post(f"/api/competitions/{comp['id']}/queue/{entry_id}/requeue")).json()['state'] == 'pending'
        patched = await client.patch(f"/api/competitions/{comp['id']}/policy",
                                     json={'max_concurrency': 3, 'auto_submit': True})
        assert patched.json()['policy']['max_concurrency'] == 3
        assert (await client.post(f"/api/competitions/{comp['id']}/tick")).status_code == 200
        assert (await client.get('/api/competitions/comp_missing')).status_code == 404
        assert (await client.post('/api/competitions', json={'connection_id': cid, 'title': 'x',
                                                             'external_competition_id': 'game-1'})).status_code == 409
        assert (await client.delete(f"/api/competitions/{comp['id']}")).json()['removed'] == comp['id']
        assert (await client.get('/api/competitions')).json() == []