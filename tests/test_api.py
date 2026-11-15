import base64
import json

import pytest
from fastapi.testclient import TestClient

from phoenix.api import create_app
from phoenix.domain import digest


@pytest.fixture
def client(components):
    with TestClient(create_app(components.settings,components)) as client:
        client.headers['Authorization']='Bearer '+components.settings.web_token
        yield client


def test_authentication_required(client):
    assert client.get('/health',headers={'Authorization':''}).status_code==200
    assert client.get('/api/overview',headers={'Authorization':''}).status_code==401
    assert client.get('/openapi.json',headers={'Authorization':''}).status_code==401


def test_origin_guard(client):
    assert client.get('/api/overview',headers={'Origin':'https://evil.invalid'}).status_code==403


def test_no_secrets_in_public_settings(client,monkeypatch):
    monkeypatch.setenv('PHOENIX_API_KEY','sk-test-secret')
    result=client.get('/api/settings')
    assert result.status_code==200 and 'sk-test-secret' not in result.text
    assert result.json()['profiles']['default']['key_configured']


def test_challenge_upload_and_freeze(client,components):
    # UI creation does not need a separate authorization acknowledgement.
    cid=client.post('/api/challenges',json={'title':'test','description':'inspect'}).json()['id']
    result=client.post(f'/api/challenges/{cid}/files',json={'name':'payload.txt','data_base64':base64.b64encode(b'123').decode()})
    assert result.status_code==200
    from phoenix.domain import RunInput
    components.store.create_run(cid,RunInput())
    assert client.post(f'/api/challenges/{cid}/files',json={'name':'new.txt','data_base64':'eA=='}).status_code==409


def test_bad_upload_path_rejected(client):
    cid=client.post('/api/challenges',json={'title':'test','description':'inspect','authorized':True}).json()['id']
    assert client.post(f'/api/challenges/{cid}/files',json={'name':'../escape','data_base64':'eA=='}).status_code==422


def test_verifier_hidden_from_challenge(client):
    cid=client.post('/api/challenges',json={'title':'test','description':'inspect','authorized':True}).json()['id']
    sha=digest('flag{hidden}')
    assert client.post(f'/api/challenges/{cid}/verifier',json={'expected_sha256':sha}).status_code==200
    assert sha not in client.get(f'/api/challenges/{cid}').text


def test_knowledge_import_review(client):
    r=client.post('/api/knowledge',json={'title':'Example','body':'unrevieweduniqueterm'})
    did=r.json()['document_id']
    assert client.get('/api/knowledge/search?q=unrevieweduniqueterm').json()==[]
    assert client.post(f'/api/knowledge/{did}/review',json={'approved':True}).status_code==200
    assert client.get('/api/knowledge/search?q=unrevieweduniqueterm').json()[0]['doc_id']==did


def test_native_demo_api_and_evidence_export(client):
    result=client.post('/api/demo')
    assert result.status_code==200 and result.json()['state']=='solved'
    rid=result.json()['id']
    detail=client.get(f'/api/runs/{rid}').json()
    assert len(detail['evidence'])==3
    eid=detail['evidence'][0]['id']
    assert client.get(f'/api/runs/{rid}/evidence/{eid}').status_code==200
    assert 'SCRIPTED' not in detail['run']['reason']  # Mode is separately recorded, never inferred from prose.
    text=client.get(f'/api/runs/{rid}/writeup/evidence').text
    assert 'Mode: **demo**' in text and 'evidence export' in text


def test_memory_to_candidate_route(client):
    client.post('/api/demo')
    memory=client.get('/api/memories').json()[0]
    mid=memory['id']
    assert client.post(f'/api/memories/{mid}/strategy',json={'key':'misc-baseline'}).status_code==422
    assert client.post(f'/api/memories/{mid}/review',json={'approved':True}).status_code==200
    result=client.post(f'/api/memories/{mid}/strategy',json={'key':'misc-baseline'})
    assert result.status_code==200 and result.json()['state']=='candidate'


def test_paid_index_confirmation(client):
    did=client.get('/api/knowledge').json()[0]['id']
    assert client.post(f'/api/knowledge/{did}/index',json={}).status_code==422


def test_audit_is_recorded_for_review(client,components):
    did=client.get('/api/knowledge').json()[0]['id']
    client.post(f'/api/knowledge/{did}/review',json={'approved':False})
    assert components.store.all("SELECT * FROM audit WHERE action='knowledge.review'")
