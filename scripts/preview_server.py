"""Local browser-test server. Scripted models; real API, store, tools and evidence.

Run on Linux/WSL with dev dependencies. No paid model calls are made.
PHOENIX_PREVIEW_DATA can select a separate test-only data directory.
"""
import asyncio
import json
import os
from pathlib import Path
import sys

def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from phoenix.api import create_app
    from phoenix.config import ModelProfile, Settings
    from phoenix.domain import ChallengeInput, RunInput
    from phoenix.service import Components
    from phoenix.swarm_demo import SwarmDemonstrationProvider, create_swarm_demo

    os.environ['PHOENIX_WEB_TOKEN'] = 'phoenix-local-browser-fixture-token-2026'
    root = Path(os.environ.get('PHOENIX_PREVIEW_DATA', '.preview-data')).resolve()
    settings = Settings(data_dir=root, port=18850, profiles={'default': ModelProfile(model='SCRIPTED-fixture')})
    c = Components(settings, SwarmDemonstrationProvider())
    result = asyncio.run(create_swarm_demo(c))
    ch = c.store.create_challenge(ChallengeInput(title='Conversation delivery / SCRIPTED fixture', category='misc',
        description='Local browser fixture for durable operator messages. No external service.', authorized=True))
    paused = c.store.create_run(ch['id'], RunInput(auto_distill=False), mode='demo')
    c.runtime.swarm.ensure(paused['id'])
    c.store.state(paused['id'], 'paused', 'SCRIPTED browser fixture, paused for operator input')
    metadata = {'demo_run_id': result['id'], 'paused_run_id': paused['id'], 'scripted': True}
    # UI-only fixtures have no model job and never call an external service.
    for key, state in (('ui_active', 'created'), ('ui_finished', 'exhausted'), ('ui_paused', 'paused')):
        case = c.store.create_challenge(ChallengeInput(title=f'UI interaction fixture / {key}',
            description='Browser interaction fixture only; no solving or external model requests.', authorized=True))
        fixture = c.store.create_run(case['id'], RunInput(auto_distill=False), mode='demo')
        c.store.state(fixture['id'], state, 'UI-only fixture; no model job was launched')
        metadata[key + '_run_id'] = fixture['id']
    (root / 'preview.json').write_text(json.dumps(metadata), encoding='utf-8')
    app = create_app(settings, c)

    import uvicorn
    print(json.dumps(metadata), flush=True)
    uvicorn.run(app, host='127.0.0.1', port=settings.port)


if __name__ == '__main__':
    main()
