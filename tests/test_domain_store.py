import asyncio
import concurrent.futures
import json

import pytest

from phoenix.domain import ChallengeInput, Conflict, Plan, RunInput, TaskSpec


@pytest.mark.parametrize('target', ['ftp://x', 'http://u:p@x', 'http://x/path', 'http://x?x=1',
                                  'tcp://x', 'https://x#frag', 'http://x:99999', 'http://%65xample.com'])
def test_bad_target(target):
    with pytest.raises(ValueError):
        ChallengeInput(title='x', description='a', targets=[target])


def test_normalize_origins():
    c = ChallengeInput(title='x', description='a', targets=['http://Example.com', 'https://example.com/', 'tcp://[::1]:123'])
    assert c.targets == ['http://example.com:80', 'https://example.com:443', 'tcp://[::1]:123']


@pytest.mark.parametrize('legacy', [None, False, True])
def test_project_usage_establishes_authorization(components, legacy):
    spec = ChallengeInput(title='x', description='data', **({} if legacy is None else {'authorized': legacy}))
    challenge = components.store.create_challenge(spec)
    assert challenge['authorized'] == 1
    assert challenge['description'] == 'data'


@pytest.mark.parametrize('tasks', [
    [TaskSpec(key='a', goal='inspect A', depends_on=['missing'])],
    [TaskSpec(key='a', goal='inspect A', depends_on=['a'])],
    [TaskSpec(key='a', goal='inspect A', depends_on=['b']), TaskSpec(key='b', goal='inspect B', depends_on=['a'])],
    [TaskSpec(key='a', goal='inspect A'), TaskSpec(key='a', goal='inspect B')],
    [TaskSpec(key='a', goal='inspect A'), TaskSpec(key='b', goal=' INSPECT   a ')],
])
def test_invalid_plan_atomic(components, run, tasks):
    with pytest.raises(ValueError):
        components.store.add_plan(run['id'], Plan(rationale='fixture', tasks=tasks))
    assert components.store.tasks(run['id']) == []


def test_dependency_and_stale_owner(components, run):
    s = components.store
    s.add_plan(run['id'], Plan(rationale='chain', tasks=[TaskSpec(key='a', goal='first inspection'),
                  TaskSpec(key='b', goal='review the result', depends_on=['a'], priority=100)]))
    s.state(run['id'], 'running')
    a = s.claim(run['id'], 'worker-one')
    assert a['key'] == 'a'
    assert s.claim(run['id'], 'worker-two') is None
    with pytest.raises(Conflict):
        s.finish(a['id'], 'wrong', 'done', 'spoofed')
    s.finish(a['id'], 'worker-one', 'done', 'checked')
    assert s.claim(run['id'], 'worker-two')['key'] == 'b'


def test_failed_dependency_blocks(components, run):
    s = components.store
    s.add_plan(run['id'], Plan(rationale='chain', tasks=[TaskSpec(key='a', goal='first inspection'),
                  TaskSpec(key='b', goal='review the result', depends_on=['a'])]))
    s.state(run['id'], 'running')
    a = s.claim(run['id'], 'worker')
    s.finish(a['id'], 'worker', 'failed', 'no result')
    assert s.claim(run['id'], 'worker') is None
    assert next(t for t in s.tasks(run['id']) if t['key'] == 'b')['state'] == 'blocked'


def test_concurrent_claim_exactly_once(components, run):
    s = components.store
    s.add_plan(run['id'], Plan(rationale='claim', tasks=[TaskSpec(key='a', goal='inspect original')]))
    s.state(run['id'], 'running')
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda i: s.claim(run['id'], str(i)), range(8)))
    assert sum(t is not None for t in claimed) == 1


def test_recovery_requires_ack(components, run, task):
    s = components.store
    assert s.recover() == [run['id']]
    assert s.run(run['id'])['state'] == 'interrupted'
    assert s.tasks(run['id'])[0]['state'] == 'interrupted'
    with pytest.raises(ValueError):
        s.resume(run['id'], False)
    s.resume(run['id'], True)
    assert s.tasks(run['id'])[0]['state'] == 'pending'


def test_resume_refuses_uncertain_container(components, run, task):
    s = components.store
    s.execute('INSERT INTO executions VALUES(?,?,?,?,?,?)', ('e1',run['id'],task['id'],'phoenix-job_x','running',0))
    s.recover()
    with pytest.raises(Conflict):
        s.resume(run['id'], True)


def test_completed_tasks_not_replayed(components, run, task):
    s = components.store
    s.finish(task['id'], 'test-owner', 'done', 'finished')
    s.recover(); s.resume(run['id'], True); s.state(run['id'], 'running')
    assert s.claim(run['id'], 'new-owner') is None


def test_input_fingerprint_stable(components, run):
    s = components.store
    assert s.freeze(run['challenge_id']) == s.freeze(run['challenge_id'])


def test_seed_idempotence(components):
    from phoenix.bootstrap import seed
    seed(components.knowledge, components.evolution)
    assert components.store.one('SELECT COUNT(*) AS n FROM skills')['n'] == 6
    assert components.store.one('SELECT COUNT(*) AS n FROM documents')['n'] == 12


def test_empty_env_values_preserve_yaml_model_settings(tmp_path, monkeypatch):
    from phoenix.config import load_settings
    config = tmp_path / 'config.yaml'
    config.write_text('profiles:\n  default:\n    model: yaml-model\n    base_url: http://localhost:8088/v1\n')
    monkeypatch.setenv('PHOENIX_MODEL', '')
    monkeypatch.setenv('PHOENIX_BASE_URL', '')
    loaded = load_settings(config)
    assert loaded.profile('solver').model == 'yaml-model'
    assert loaded.profile('solver').base_url == 'http://localhost:8088/v1'


def test_environment_endpoint_override_is_validated(tmp_path, monkeypatch):
    from phoenix.config import load_settings
    monkeypatch.setenv('PHOENIX_BASE_URL', 'http://user:secret@localhost/v1')
    with pytest.raises(ValueError):
        load_settings(tmp_path / 'no-config.yaml')
