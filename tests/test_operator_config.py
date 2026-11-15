import json

import httpx
import pytest

from phoenix.api import create_app
from phoenix.config import load_settings
from phoenix.domain import RunInput


@pytest.fixture
def client(components):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(components.settings, components)),
        base_url='http://test', headers={'Authorization': 'Bearer ' + components.settings.web_token})


@pytest.mark.asyncio
async def test_native_configuration_persists_without_exposing_credentials(components, client, monkeypatch):
    monkeypatch.setenv('PHOENIX_TEST_KEY', '')
    profiles = {k: v.model_dump() for k, v in components.settings.profiles.items()}
    profiles['default'].update(model='', api_key_env='PHOENIX_TEST_KEY')
    async with client:
        result = await client.post('/api/configuration', json={'profiles': profiles,
            'secrets': {'PHOENIX_TEST_KEY': 'local-fixture-value'}})
        assert result.status_code == 200
        assert result.json()['profiles']['default']['key_configured']
        assert 'local-fixture-value' not in result.text
        assert (await client.get('/api/settings')).json()['profiles']['default']['model'] == ''
    config = components.settings.data_dir / 'config.yaml'
    config.write_text('data_dir: ' + str(components.settings.data_dir), encoding='utf-8')
    restored = load_settings(config)
    assert restored.profiles['default'].model == ''
    assert restored.profiles['default'].key == 'local-fixture-value'
    assert 'local-fixture-value' not in json.dumps(components.store.all('SELECT * FROM audit'))


@pytest.mark.asyncio
async def test_bad_configuration_is_atomic_and_cannot_change_service_token(components, client):
    async with client:
        for value in ({'secrets': {'PHOENIX_WEB_TOKEN': 'replaced'}},
                      {'profiles': {}}, {'roles': {'solver': 'missing'}},
                      {'workers': [components.settings.workers[0].model_dump()] * 2}):
            assert (await client.post('/api/configuration', json=value)).status_code == 422
        assert not (components.settings.data_dir / 'operator-config.json').exists()
        assert not (components.settings.data_dir / 'model-credentials.json').exists()
        assert (await client.post('/api/configuration', json={}, headers={'Authorization': ''})).status_code == 401


@pytest.mark.asyncio
async def test_hot_update_succeeds_while_live_run_keeps_snapshot(components, run, client):
    components.runtime.swarm.ensure(run['id'])
    before_worker = components.store.all('SELECT profiles FROM swarm_workers WHERE run_id=?', (run['id'],))
    before_planner = components.store.run_profile(run['id'], 'planner')
    profiles = {k: v.model_dump() for k, v in components.settings.profiles.items()}
    profiles['default']['model'] = 'rotated-model'
    profiles['default']['context_tokens'] = 65536
    async with client:
        # An active live run no longer blocks shared configuration changes.
        result = await client.post('/api/configuration', json={'profiles': profiles})
        assert result.status_code == 200
        assert result.json()['profiles']['default']['model'] == 'rotated-model'
    # The in-flight run keeps its frozen worker and coordinator snapshots.
    assert components.store.all('SELECT profiles FROM swarm_workers WHERE run_id=?', (run['id'],)) == before_worker
    assert components.store.run_profile(run['id'], 'planner') == before_planner
    assert before_planner['model'] == 'fixture-model'
    # A newly created run picks up the hot-updated configuration.
    fresh = components.store.create_run(run['challenge_id'], RunInput(auto_distill=False))
    components.runtime.swarm.ensure(fresh['id'])
    assert components.store.run_profile(fresh['id'], 'planner')['model'] == 'rotated-model'


@pytest.mark.asyncio
async def test_hot_update_deleting_profile_does_not_break_resumable_run(components, run, client):
    components.runtime.swarm.ensure(run['id'])
    profiles = {k: v.model_dump() for k, v in components.settings.profiles.items()}
    profiles['spare'] = {**profiles['default'], 'model': 'spare-model'}
    roles = dict(components.settings.roles)
    async with client:
        assert (await client.post('/api/configuration', json={'profiles': profiles, 'roles': roles})).status_code == 200
        # Removing the extra profile again is allowed; the active run never referenced it live.
        del profiles['spare']
        assert (await client.post('/api/configuration', json={'profiles': profiles})).status_code == 200
    assert components.store.run_profile(run['id'], 'planner')['model'] == 'fixture-model'


@pytest.mark.asyncio
async def test_original_phoenix_preferences_contract_versions_validation_and_restart(components, client):
    async with client:
        assert (await client.get('/api/health')).json()['features']['ui.preferences'] == 1
        assert (await client.get('/api/settings/ui')).json() == {'version': 0, 'values': {}}
        value = {'version': 0, 'values': {'theme': 'light', 'readingFontScale': 'lg',
            'readingContentWidth': 'wide', 'accent': {'kind': 'custom', 'hue': 225}}}
        result = await client.put('/api/settings/ui', json=value)
        assert result.status_code == 200
        assert result.json()['version'] == 1
        conflict = await client.put('/api/settings/ui', json=value)
        assert conflict.status_code == 409
        assert conflict.json() == result.json()
        for bad in ({'theme': 'rainbow'}, {'server_command': 'bad'}, {'accent': {'kind': 'custom', 'hue': 360}},
                    {'diffWrap': 'true'}):
            assert (await client.put('/api/settings/ui', json={'version': 1, 'values': bad})).status_code == 422
        assert (await client.put('/api/settings/ui', json=value, headers={'Authorization': ''})).status_code == 401
    # A new application instance reads the persisted contract, with the same version.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(components.settings, components)),
            base_url='http://test', headers={'Authorization': 'Bearer ' + components.settings.web_token}) as reopened:
        assert (await reopened.get('/api/settings/ui')).json() == result.json()
