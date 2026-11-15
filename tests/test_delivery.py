"""Distribution, service supervisor and native UI mutation contracts."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from phoenix.api import create_app
from phoenix.config import Settings
from phoenix.domain import digest
from phoenix.swarm_demo import create_swarm_demo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('phoenix_supervisor', ROOT / 'scripts/serve.py')
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)


def test_default_and_heterogeneous_config_are_valid():
    import yaml
    for name in ('config.example.yaml', 'config.swarm.example.yaml'):
        config = Settings.model_validate(yaml.safe_load((ROOT / name).read_text()))
        assert len(config.workers) == 4
        assert config.port == 18750


def test_frontend_start_modes_require_real_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor.shutil, 'which', lambda _: '/bin/node')
    with pytest.raises(ValueError, match='not built'):
        supervisor.frontend_command(tmp_path, False, '127.0.0.1', 3001)
    with pytest.raises(ValueError, match='dependencies are missing'):
        supervisor.frontend_command(tmp_path, True, '127.0.0.1', 3001)
    entry = tmp_path / 'frontend/node_modules/next/dist/bin/next'
    entry.parent.mkdir(parents=True)
    entry.write_text('fixture only')
    assert supervisor.frontend_command(tmp_path, True, '127.0.0.1', 3001)[-4:] == ['-H', '127.0.0.1', '-p', '3001']
    monkeypatch.setattr(supervisor.shutil, 'which', lambda _: None)
    with pytest.raises(ValueError, match='Node.js'):
        supervisor.frontend_command(tmp_path, False, '127.0.0.1', 3001)


def test_supervisor_stops_its_child():
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
    try:
        supervisor.stop_children([child], timeout=1)
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_frontend_manifest_and_routes_are_native():
    ui = ROOT / 'frontend'
    manifest = json.loads((ui / 'public/manifest.json').read_text())
    assert manifest['start_url'] == '/ctf'
    assert all(item['url'] != '/chat' for item in manifest['shortcuts'])
    for route in ('ctf', 'swarm', 'knowledge', 'memory', 'evolution', 'settings'):
        assert (ui / 'app' / route / 'page.tsx').is_file()
    assert not (ui / 'app/api/workspace-browser-proxy').exists()
    # Audit shipped source, not installed dependency fonts or generated build output.
    assert not [p for p in ui.rglob('*.woff2') if not any(
        part == 'node_modules' or part.startswith('.next') for part in p.relative_to(ui).parts)]


@pytest.mark.asyncio
async def test_receipt_reconciles_settled_run_and_emits_event(components):
    result = await create_swarm_demo(components)
    rid = result['id']
    cid = components.store.one('SELECT id FROM candidates WHERE run_id=?', (rid,))['id']
    transport = httpx.ASGITransport(app=create_app(components.settings, components))
    async with httpx.AsyncClient(transport=transport, base_url='http://test',
                                headers={'Authorization': 'Bearer ' + components.settings.web_token}) as client:
        response = await client.post(f'/api/candidates/{cid}/receipt', json={'accepted': False, 'receipt': 'Fixture operator rejects previously accepted value'})
        assert response.status_code == 200
        assert response.json()['run_state'] == 'awaiting_verification'
        response = await client.post(f'/api/candidates/{cid}/receipt', json={'accepted': True, 'receipt': 'Fixture operator reports platform acceptance'})
        assert response.status_code == 200
        assert response.json()['run_state'] == 'solved'
    assert components.store.one('SELECT outcome FROM episodes WHERE run_id=?', (rid,))['outcome'] == 'solved'
    events = components.store.all("SELECT payload FROM events WHERE run_id=? AND kind='flag.operator_receipt'", (rid,))
    assert len(events) == 2
    assert json.loads(events[0]['payload'])['verification_source'] == 'operator-reported'
