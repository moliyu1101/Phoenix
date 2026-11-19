import pytest
from fastapi.testclient import TestClient

from phoenix.api import create_app

TOKEN = 'test-secret-token-at-least-32-characters'


@pytest.fixture
def app(components):
    return create_app(components.settings, components)


def test_login_wrong_password(app):
    with TestClient(app) as client:
        assert client.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401


def test_login_sets_cookie_and_protocol2(app):
    with TestClient(app) as client:
        response = client.post('/api/auth/login', json={'password': TOKEN, 'remember': True, 'client': 'web'})
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert data['session_protocol'] == 2
        assert data['session_owner'] == 'cookie'
        assert 'token' not in data
        assert data['service_id'] and data['identity_id']
        assert data['auth_required'] is True
        assert isinstance(data['expires_at'], int)
        assert data['persistence_warning']
        assert 'phoenix_session' in response.cookies


def test_cookie_session_accesses_api_without_bearer(app):
    with TestClient(app) as client:
        client.post('/api/auth/login', json={'password': TOKEN})
        assert client.get('/api/overview').status_code == 200


def test_me_returns_identity(app):
    with TestClient(app) as client:
        client.post('/api/auth/login', json={'password': TOKEN})
        data = client.get('/api/auth/me').json()
        assert data['authenticated'] is True
        assert data['session_protocol'] == 2
        assert data['service_id'] and data['identity_id']
        assert isinstance(data['expires_at'], int)


def test_me_unauthenticated(app):
    with TestClient(app) as client:
        assert client.get('/api/auth/me').status_code == 401


def test_bearer_still_works(app):
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        assert client.get('/api/overview').status_code == 200
        data = client.get('/api/auth/me').json()
        assert data['authenticated'] is True
        assert data['expires_at'] is None


def test_logout_revokes_session(app):
    with TestClient(app) as client:
        client.post('/api/auth/login', json={'password': TOKEN})
        assert client.get('/api/overview').status_code == 200
        assert client.post('/api/auth/logout').status_code == 200
        assert client.get('/api/auth/me').status_code == 401


def test_ticket_is_one_time(app):
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        ticket = client.post('/api/auth/ticket').json()['ticket']
        assert ticket
        first = client.get('/api/overview', params={'ticket': ticket}, headers={'Authorization': ''})
        assert first.status_code == 200
        replay = client.get('/api/overview', params={'ticket': ticket}, headers={'Authorization': ''})
        assert replay.status_code == 401


def test_login_exempt_from_credential_check(app):
    with TestClient(app) as client:
        assert client.post('/api/auth/login', json={'password': TOKEN}).status_code == 200


def test_access_config_shape(app):
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        cfg = client.get('/api/settings/access').json()
        assert cfg['auth_required'] is True
        assert cfg['source'] in ('settings', 'environment', 'none')
        assert isinstance(cfg['environment_configured'], bool)
        assert isinstance(cfg['has_override'], bool)
        assert isinstance(cfg['session_ttl_seconds'], int)
        assert isinstance(cfg['can_disable'], bool)
        assert cfg['service_id']


def test_access_rotate_password(app):
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        result = client.put('/api/settings/access',
                            json={'action': 'set', 'current_password': TOKEN, 'new_password': 'brand-new-password'})
        assert result.status_code == 200
        assert result.json()['source'] == 'settings'
        assert result.json()['has_override'] is True
        assert client.post('/api/auth/login', json={'password': TOKEN}).status_code == 401
        assert client.post('/api/auth/login', json={'password': 'brand-new-password'}).status_code == 200
        inherit = client.put('/api/settings/access', json={'action': 'inherit', 'current_password': 'brand-new-password'})
        assert inherit.status_code == 200
        assert inherit.json()['has_override'] is False
        assert client.post('/api/auth/login', json={'password': TOKEN}).status_code == 200


def test_access_rotate_wrong_current(app):
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        result = client.put('/api/settings/access',
                            json={'action': 'set', 'current_password': 'nope', 'new_password': 'brand-new-password'})
        assert result.status_code == 401


def test_access_weak_password(app):
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        result = client.put('/api/settings/access',
                            json={'action': 'set', 'current_password': TOKEN, 'new_password': 'short'})
        assert result.status_code == 422


def test_env_password_login(app, monkeypatch):
    monkeypatch.setenv('PHOENIX_WEB_PASSWORD', 'env-password-value')
    with TestClient(app) as client:
        assert client.post('/api/auth/login', json={'password': 'env-password-value'}).status_code == 200
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        assert client.get('/api/settings/access').json()['source'] == 'environment'