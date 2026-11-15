import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from phoenix.domain import Conflict, NotFound, dump
from phoenix.extensions import Extensions, normalize_config
from phoenix.extensions_api import attach_extensions


class FakeSession:
    def __init__(self, tools=None, result=None, fail_list=False, fail_call=False):
        self.tools = tools if tools is not None else [
            SimpleNamespace(name='echo', description='Echo the input', input_schema={'type': 'object', 'properties': {}})]
        self.result = result if result is not None else SimpleNamespace(
            content=[SimpleNamespace(type='text', text='ok')], is_error=False, structured_content=None)
        self.fail_list, self.fail_call, self.calls = fail_list, fail_call, []

    async def initialize(self):
        return None

    async def list_tools(self):
        if self.fail_list:
            raise RuntimeError('list failed')
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name, arguments):
        if self.fail_call:
            raise RuntimeError('call failed')
        self.calls.append((name, arguments))
        return self.result


def factory(session=None, connect_error=None):
    @asynccontextmanager
    async def open_session(transport, config):
        if connect_error is not None:
            raise connect_error
        yield session if session is not None else FakeSession()
    return open_session


@pytest.fixture
def ext(components):
    service = Extensions(components)
    service.session_factory = factory()
    return service


def stdio_spec(name='local', **overrides):
    spec = {'name': name, 'transport': 'stdio',
            'config': {'command': 'echo-server', 'args': ['--stdio'], 'env': {'TOKEN': 'super-secret-value'}}}
    spec.update(overrides)
    return spec


def test_crud_and_secret_non_echo(ext):
    created = ext.create_server(stdio_spec())
    sid = created['id']
    assert created['state'] == 'unknown' and created['enabled'] is False
    assert created['config']['env_keys'] == ['TOKEN']
    assert 'super-secret-value' not in dump(created)
    assert 'env' not in created['config'] and 'headers' not in created['config']
    stored = ext.store.one('SELECT config FROM mcp_servers WHERE id=?', (sid,))
    assert json.loads(stored['config'])['env']['TOKEN'] == 'super-secret-value'
    assert len(ext.list_servers()) == 1
    renamed = ext.update_server(sid, {'name': 'renamed'})
    assert renamed['name'] == 'renamed'
    assert json.loads(ext.store.one('SELECT config FROM mcp_servers WHERE id=?', (sid,))['config'])['env']['TOKEN'] == 'super-secret-value'
    with pytest.raises(Conflict):
        ext.create_server(stdio_spec(name='renamed'))
    assert ext.delete_server(sid) == {'removed': sid}
    with pytest.raises(NotFound):
        ext.server(sid)


def test_remote_config_validation_and_secret_clear(ext):
    with pytest.raises(ValueError):
        normalize_config('streamable-http', {'url': 'ftp://example.test/mcp'})
    with pytest.raises(ValueError):
        normalize_config('streamable-http', {'url': 'http://user:pass@example.test/mcp'})
    created = ext.create_server({'name': 'remote', 'transport': 'streamable-http',
                                 'config': {'url': 'https://example.test/mcp', 'headers': {'Authorization': 'Bearer hidden-token'}}})
    assert created['config']['header_keys'] == ['Authorization']
    assert 'hidden-token' not in dump(created)
    cleared = ext.update_server(created['id'], {'config': {'url': 'https://example.test/mcp', 'headers': {}}})
    assert cleared['config']['header_keys'] == []


async def test_enable_disable_gating(ext, components, run, task):
    sid = ext.create_server(stdio_spec())['id']
    assert ext.schemas() == []
    with pytest.raises(Conflict):
        await ext.call_tool(sid, 'echo', {}, rid=run['id'], tid=task['id'])
    ext.set_server_enabled(sid, True)
    assert ext.schemas() == []  # not probed yet -> no discovered tools
    ext.store.execute("UPDATE mcp_servers SET state='healthy',tools=? WHERE id=?",
                      (dump([{'name': 'echo', 'description': '', 'input_schema': {'type': 'object'}}]), sid))
    assert len(ext.schemas()) == 1
    ext.set_server_enabled(sid, False)
    assert ext.schemas() == []


async def test_probe_success_and_failure(ext):
    session = FakeSession()
    ext.session_factory = factory(session)
    sid = ext.create_server(stdio_spec())['id']
    healthy = await ext.probe(sid)
    assert healthy['state'] == 'healthy' and healthy['tool_count'] == 1
    assert healthy['tools'][0]['name'] == 'echo' and healthy['error'] == ''
    ext.session_factory = factory(FakeSession(fail_list=True))
    failed = await ext.probe(sid)
    assert failed['state'] == 'error' and 'list failed' in failed['error']
    ext.session_factory = factory(connect_error=OSError('connection refused'))
    crashed = await ext.probe(sid)
    assert crashed['state'] == 'error' and 'connection refused' in crashed['error']
    assert crashed['tool_count'] == 0
    assert ext.overview()['mcp_servers']['error'] == 1


async def test_tool_call_records_evidence_and_flag(ext, components, run, task):
    session = FakeSession(result=SimpleNamespace(
        content=[SimpleNamespace(type='text', text='result flag{mcp-evidence}')], is_error=False, structured_content=None))
    ext.session_factory = factory(session)
    sid = ext.create_server(stdio_spec())['id']
    ext.set_server_enabled(sid, True)
    await ext.probe(sid)
    result = await ext.call_tool(sid, 'echo', {'input': 'hello'}, rid=run['id'], tid=task['id'])
    assert result['ok'] and result['origin'] == 'tool' and result['evidence_id']
    row = components.store.one('SELECT * FROM evidence WHERE id=?', (result['evidence_id'],))
    assert row['origin'] == 'tool' and row['run_id'] == run['id'] and row['task_id'] == task['id']
    assert 'flag{mcp-evidence}' in row['content']
    assert result['candidate_ids']
    assert session.calls == [('echo', {'input': 'hello'})]
    assert 'super-secret-value' not in row['content'] and 'super-secret-value' not in row['arguments']


async def test_tool_call_failure_records_error_evidence(ext, components, run, task):
    ext.session_factory = factory(FakeSession(fail_call=True))
    sid = ext.create_server(stdio_spec())['id']
    ext.set_server_enabled(sid, True)
    await ext.probe(sid)
    result = await ext.call_tool(sid, 'echo', {}, rid=run['id'], tid=task['id'])
    assert result['ok'] is False and result['evidence_id']
    row = components.store.one('SELECT ok,content FROM evidence WHERE id=?', (result['evidence_id'],))
    assert row['ok'] == 0 and 'call failed' in row['content']


async def test_bridge_schemas_and_call(ext, components, run, task):
    ext.session_factory = factory()
    sid = ext.create_server(stdio_spec(name='my server'))['id']
    ext.set_server_enabled(sid, True)
    await ext.probe(sid)
    schemas = ext.schemas()
    assert len(schemas) == 1
    name = schemas[0]['function']['name']
    assert name.startswith('mcp__') and len(name) <= 64
    assert schemas[0]['function']['parameters']['type'] == 'object'
    result = await ext.call(run['id'], task['id'], name, {'input': 'bridge'})
    assert result['ok'] and result['origin'] == 'tool' and result['evidence_id']
    with pytest.raises(ValueError):
        await ext.call(run['id'], task['id'], 'mcp__missing__tool', {})


async def test_operator_call_without_run(ext):
    ext.session_factory = factory()
    sid = ext.create_server(stdio_spec())['id']
    ext.set_server_enabled(sid, True)
    await ext.probe(sid)
    result = await ext.call_tool(sid, 'echo', {'input': 'x'})
    assert result['ok'] and 'evidence_id' not in result and result['result']['content'][0]['text'] == 'ok'
    with pytest.raises(ValueError):
        await ext.call_tool(sid, 'undiscovered', {})


def test_plugin_crud_and_enable(ext):
    created = ext.create_plugin({'manifest': {'name': 'demo', 'version': '1.0.0', 'description': '演示插件'}})
    pid = created['id']
    assert created['name'] == 'demo' and created['enabled'] is False
    assert ext.set_plugin_enabled(pid, True)['enabled'] is True
    assert ext.overview()['plugins'] == {'total': 1, 'enabled': 1}
    with pytest.raises(Conflict):
        ext.create_plugin({'manifest': {'name': 'demo'}})
    assert ext.delete_plugin(pid) == {'removed': pid}
    with pytest.raises(NotFound):
        ext.plugin(pid)


def test_plugin_from_package_path(ext, tmp_path):
    package = tmp_path / 'demo-plugin'
    package.mkdir()
    (package / 'plugin.json').write_text(json.dumps({
        '$schema': 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',
        'name': 'packaged-demo', 'version': '1.0.0', 'description': 'A packaged plugin'}), encoding='utf-8')
    created = ext.create_plugin({'path': str(package)})
    assert created['name'] == 'packaged-demo' and created['source'] == str(package)
    assert created['manifest']['version'] == '1.0.0'
    with pytest.raises(ValueError):
        ext.create_plugin({'path': str(tmp_path / 'missing')})


def test_overview_counts(ext):
    ext.create_server(stdio_spec(name='a'))
    ext.create_server(stdio_spec(name='b'))
    ext.create_plugin({'manifest': {'name': 'p'}})
    overview = ext.overview()
    assert overview['mcp_servers']['total'] == 2 and overview['mcp_servers']['enabled'] == 0
    assert overview['plugins']['total'] == 1 and overview['tools'] == 0
    assert overview['sdk'] in ('mcp', 'unavailable')


@pytest.fixture
def client(components):
    app = FastAPI()
    attach_extensions(app, components)
    components.extensions.session_factory = factory()
    return TestClient(app)


def test_api_contract(client):
    assert client.get('/api/extensions/overview').status_code == 200
    created = client.post('/api/extensions/mcp-servers', json=stdio_spec())
    assert created.status_code == 200
    sid = created.json()['id']
    assert 'super-secret-value' not in created.text
    assert client.get('/api/extensions/mcp-servers').json()['servers'][0]['id'] == sid
    assert client.get(f'/api/extensions/mcp-servers/{sid}').status_code == 200
    assert client.patch(f'/api/extensions/mcp-servers/{sid}', json={'name': 'api-renamed'}).json()['name'] == 'api-renamed'
    assert client.post(f'/api/extensions/mcp-servers/{sid}/enabled', json={'enabled': True}).json()['enabled'] is True
    probed = client.post(f'/api/extensions/mcp-servers/{sid}/probe')
    assert probed.json()['state'] == 'healthy'
    assert client.get('/api/extensions/tools').json()['tools']
    called = client.post(f'/api/extensions/mcp-servers/{sid}/call', json={'name': 'echo', 'arguments': {'input': 'x'}})
    assert called.json()['ok'] is True
    assert client.delete(f'/api/extensions/mcp-servers/{sid}').json() == {'removed': sid}
    assert client.get(f'/api/extensions/mcp-servers/{sid}').status_code == 404
    plugin = client.post('/api/extensions/plugins', json={'manifest': {'name': 'api-plugin'}})
    pid = plugin.json()['id']
    assert client.post(f'/api/extensions/plugins/{pid}/enabled', json={'enabled': True}).json()['enabled'] is True
    assert client.delete(f'/api/extensions/plugins/{pid}').json() == {'removed': pid}
    assert client.post('/api/extensions/mcp-servers', json={'name': 'bad', 'transport': 'stdio', 'config': {}}).status_code == 422