import base64
from pathlib import Path

import pytest

from phoenix.config import ModelProfile, Settings
from phoenix.demo import DemonstrationProvider
from phoenix.domain import ChallengeInput, Plan, RunInput, TaskSpec
from phoenix.service import Components


@pytest.fixture
def components(tmp_path, monkeypatch):
    monkeypatch.setenv('PHOENIX_WEB_TOKEN', 'test-secret-token-at-least-32-characters')
    settings = Settings(data_dir=tmp_path, profiles={'default': ModelProfile(model='fixture-model')})
    return Components(settings, DemonstrationProvider())


@pytest.fixture
def run(components):
    c = components.store.create_challenge(ChallengeInput(title='Fixture challenge', category='misc',
                                         description='Inspect a provided attachment', authorized=True))
    return components.store.create_run(c['id'], RunInput(auto_distill=False))


@pytest.fixture
def task(components, run):
    s = components.store
    s.add_plan(run['id'], Plan(rationale='test', tasks=[TaskSpec(key='first', goal='Inspect the original data')]))
    s.state(run['id'], 'running')
    return s.claim(run['id'], 'test-owner')
