import pytest
from fastapi.testclient import TestClient

from phoenix.api import create_app
from phoenix.domain import Quote


@pytest.fixture
def client(components):
    with TestClient(create_app(components.settings, components)) as client:
        client.headers['Authorization'] = 'Bearer ' + components.settings.web_token
        yield client


def test_demo_writeup_generation_view_export(client, components):
    rid = client.post('/api/demo').json()['id']
    assert client.get(f'/api/runs/{rid}/writeup').status_code == 404
    # Demo mode is scripted and incurs no real charges, so no paid confirmation is needed.
    result = client.post(f'/api/runs/{rid}/writeup', json={})
    assert result.status_code == 200
    record = result.json()
    assert record['verified_outcome'] is True
    assert record['model'] == 'fixture-model'
    assert record['citations'] and record['doc']['steps']
    for needle in ('## 概述', '## 题目分析', '## 解题步骤', '## 复现检查', '## 引用证据'):
        assert needle in record['body']
    # Every stored citation binds to an unchanged immutable observation.
    components.evidence.validate_quotes(rid, [Quote.model_validate(q) for q in record['citations']])
    assert client.get(f'/api/runs/{rid}/writeup').json()['title'] == record['title']
    export = client.get(f'/api/runs/{rid}/writeup/export')
    assert export.status_code == 200 and 'attachment' in export.headers['content-disposition']
    assert export.text == record['body']
    # Regenerating replaces the prior writeup rather than duplicating it.
    again = client.post(f'/api/runs/{rid}/writeup', json={})
    assert again.status_code == 200
    rows = components.store.all('SELECT run_id FROM writeups WHERE run_id=?', (rid,))
    assert len(rows) == 1


def test_live_writeup_requires_paid_confirmation(client, components, run, task):
    components.evidence.record(run['id'], task['id'], 'file_read', {}, 'original immutable observation')
    components.store.state(run['id'], 'solved', 'fixture terminal')
    assert client.post(f"/api/runs/{run['id']}/writeup", json={}).status_code == 422
    result = client.post(f"/api/runs/{run['id']}/writeup", json={'confirm_paid': True})
    assert result.status_code == 200
    assert result.json()['verified_outcome'] is False
    audit = components.store.all("SELECT payload FROM audit WHERE action='writeup.model_usage'")
    assert audit and audit[0]['payload'].find('operator_writeup') >= 0


def test_active_run_cannot_generate_writeup(client, run):
    assert client.post(f'/api/runs/{run["id"]}/writeup', json={'confirm_paid': True}).status_code == 409


def test_writeup_requires_original_evidence(client, components, run):
    components.store.state(run['id'], 'exhausted', 'no evidence')
    assert client.post(f'/api/runs/{run["id"]}/writeup', json={'confirm_paid': True}).status_code == 422


def test_writeup_rejects_invented_citation(components, run, task):
    import json

    from phoenix.domain import Completion

    class InventingGateway:
        settings = components.gateway.settings

        async def complete_detached(self, rid, role, messages, *, profile_override=None):
            doc = {'title': ' invented', 'overview': 'overview text', 'analysis': 'analysis text',
                   'steps': [{'heading': 'step', 'detail': 'detail text', 'citation_ids': ['ev_fake:0:bad']}],
                   'reproduction': {'reproducible': False, 'notes': 'notes text', 'gaps': []},
                   'conclusion': 'conclusion text', 'citation_ids': ['ev_fake:0:bad']}
            return Completion(text=json.dumps(doc), input_tokens=10, output_tokens=20)

    components.evidence.record(run['id'], task['id'], 'file_read', {}, 'original immutable observation')
    components.store.state(run['id'], 'solved', 'fixture terminal')
    with pytest.raises(ValueError, match='Unknown immutable excerpt'):
        import asyncio
        asyncio.run(components.writeup.generate(run['id'], InventingGateway(), confirm_paid=True))
    assert not components.store.all('SELECT * FROM writeups')