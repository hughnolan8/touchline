from fastapi.testclient import TestClient

from backend.app import api


def test_public_api_returns_empty_paper_state_without_provider_or_database_setup():
    with TestClient(api.create_app(setup=False)) as client:
        health = client.get('/health').json()
        assert health['ok'] is True and health['mode'] == 'paper'
        assert [league['code'] for league in health['leagues']] == ['E0', 'SP1', 'D1', 'I1', 'F1']
        assert client.get('/api/v1/bets').json() == {'items': []}
        assert client.get('/api/v1/predictions').json() == []
        summary = client.get('/api/v1/summary').json()
        assert summary['mode'] == 'paper'
        assert summary['recent'] == []
        assert summary['account']['balance'] == 1000.0
        assert client.get('/api/v1/engine').json()['status'] == 'overdue'
        assert client.get('/health/engine').status_code == 503
        assert client.get('/api/v1/predictions?league=SP1').json() == []
        assert client.get('/api/v1/predictions?league=unknown').status_code == 422


def test_manual_refresh_endpoints_release_their_lease(monkeypatch):
    calls = []
    monkeypatch.setattr(api, 'acquire', lambda name, seconds: calls.append(('acquire', name, seconds)) or 'token')
    monkeypatch.setattr(api, 'release', lambda name, token: calls.append(('release', name, token)))
    monkeypatch.setattr(api, 'refresh_all', lambda: {'refreshed': 1})
    monkeypatch.setattr(api, 'refresh_missing_odds', lambda: {'requested': 1})
    with TestClient(api.create_app(setup=False)) as client:
        assert client.post('/api/v1/refresh-all').json() == {'refreshed': 1}
        assert client.post('/api/v1/refresh-missing-odds').json() == {'requested': 1}
    assert calls == [
        ('acquire', 'manual-refresh', 300), ('release', 'manual-refresh', 'token'),
        ('acquire', 'missing-odds-refresh', 300), ('release', 'missing-odds-refresh', 'token'),
    ]


def test_manual_refresh_rejects_an_existing_lease(monkeypatch):
    monkeypatch.setattr(api, 'acquire', lambda *_, **__: None)
    with TestClient(api.create_app(setup=False)) as client:
        response = client.post('/api/v1/refresh-all')
    assert response.status_code == 409
    assert response.json()['detail'] == 'A refresh is already running'
