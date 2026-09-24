from backend.app import engine
from backend.app import api
from backend.app.store import initialize
from backend.db import connect
from backend.providers import ingest_match,add_quote
from fastapi.testclient import TestClient


def test_initialize_renames_legacy_app_state():
    with connect() as connection:
        connection.execute('DROP INDEX app_jobs_due')
        connection.execute('ALTER TABLE app_leases RENAME TO mobile_leases')
        connection.execute('ALTER TABLE app_jobs RENAME TO mobile_jobs')
        connection.execute("UPDATE settings SET key='mobile_initialized' WHERE key='app_initialized'")
    initialize()
    with connect() as connection:
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_leases'").fetchone()
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_jobs'").fetchone()
        assert connection.execute("SELECT 1 FROM settings WHERE key='app_initialized'").fetchone()
        assert not connection.execute("SELECT 1 FROM settings WHERE key='mobile_initialized'").fetchone()


def test_bootstrap_syncs_active_and_prior_three_understat_seasons(monkeypatch):
    calls = []

    def sync(connection, league, seasons):
        calls.append((league, list(seasons)))
        return 0

    monkeypatch.setattr(engine, 'sync_seasons', sync)
    assert engine.bootstrap('2026-09-17T12:00:00+00:00') is True
    assert calls == [(league, [2023, 2024, 2025, 2026]) for league in ('E0', 'SP1', 'D1', 'I1', 'F1')]
    assert engine.bootstrap('2026-09-17T12:00:00+00:00') is False


def test_current_season_refresh_uses_understat(monkeypatch):
    calls = []

    def sync(connection, league, seasons):
        calls.append((league, list(seasons)))
        return 42

    monkeypatch.setattr(engine, 'sync_seasons', sync)
    assert engine.import_scores('2026-02-01T12:00:00+00:00') == 210
    assert calls == [(league, [2025]) for league in ('E0', 'SP1', 'D1', 'I1', 'F1')]


def test_refresh_missing_odds_only_calls_provider_when_a_market_is_missing(monkeypatch):
    at = '2026-09-17T12:00:00+00:00'
    with connect() as connection:
        ingest_match(connection, 'test', 'missing', 'E0', 'Arsenal', 'Chelsea', '2026-09-18T12:00:00+00:00', True, 'scheduled', {})
    calls = []

    class Odds:
        def refresh(self, fixtures, value):
            calls.append((fixtures, value))
            return 1
        def close(self):
            pass

    monkeypatch.setattr(engine, 'MobileOdds', Odds)
    assert engine.refresh_missing_odds(at) == {'requested': 1, 'fixtures': 1, 'still_missing': 1}
    assert calls[0][0][0]['id']
    assert calls[0][1] == at


def test_tick_only_places_a_bet_after_fotmob_confirms_the_lineup(monkeypatch):
    at = '2026-09-17T12:00:00+00:00'
    with connect() as connection:
        fixture=ingest_match(connection, 'test', 'lineup-window', 'E0', 'Arsenal', 'Chelsea', '2026-09-17T12:58:00+00:00', True, 'scheduled', {})
    monkeypatch.setattr(engine, 'bootstrap', lambda value: False)
    monkeypatch.setattr(engine, 'train', lambda *args: 1)
    monkeypatch.setattr(engine, 'train_player', lambda *args: 2)
    calls = []

    class Lineups:
        def refresh(self, fixtures, value):
            calls.append(('lineups', fixtures, value))
            return [fixtures[0]['id']]
        def close(self):
            pass

    class Odds:
        def refresh(self, fixtures, value):
            calls.append(('odds', fixtures, value))
            with connect() as connection:
                for selection,price in [('home',2.4),('draw',3.4),('away',3.2)]:
                    add_quote(connection,fixture,'1x2',selection,None,'','Bet365',price,value,value,'test','https://example.test',True)
            return 1
        def close(self):
            pass

    monkeypatch.setattr(engine, 'FotMobLineups', Lineups)
    monkeypatch.setattr(engine, 'MobileOdds', Odds)
    monkeypatch.setattr(engine, 'forecast', lambda *args: {'model': 'Dixon-Coles + confirmed XI', 'probabilities': {}})
    monkeypatch.setattr(engine, 'place_required_bet', lambda *args,**kwargs: 'placed')
    result = engine.tick(at)
    assert result['lineups'] == 1
    assert [call[0] for call in calls] == ['odds', 'lineups']
    with connect() as connection:
        assert connection.execute('SELECT 1 FROM fixture_odds_snapshots WHERE match_id=?',(fixture,)).fetchone()
        assert connection.execute("SELECT 1 FROM settings WHERE key LIKE 'lineup-refreshed:%'").fetchone()


def test_early_odds_window_only_prepares_forecasts(monkeypatch):
    at = '2026-09-17T12:00:00+00:00'
    with connect() as connection:
        ingest_match(connection, 'test', 'early-window', 'E0', 'Arsenal', 'Chelsea', '2026-09-17T12:58:00+00:00', True, 'scheduled', {})
    monkeypatch.setattr(engine, 'bootstrap', lambda value: False)
    monkeypatch.setattr(engine, 'train', lambda *args: 1)
    monkeypatch.setattr(engine, 'train_player', lambda *args: 2)
    monkeypatch.setattr(engine, 'forecast', lambda *args: {'model': 'Dixon-Coles', 'probabilities': {}})
    monkeypatch.setattr(engine, 'place_required_bet', lambda *args: (_ for _ in ()).throw(AssertionError('must not place early')))
    class Odds:
        def refresh(self, fixtures, value): return 1
        def close(self): pass
    class Lineups:
        def refresh(self, fixtures, value): return []
        def close(self): pass
    monkeypatch.setattr(engine, 'MobileOdds', Odds)
    monkeypatch.setattr(engine, 'FotMobLineups', Lineups)
    result = engine.tick(at)
    assert result['refreshed'] == 1


def test_engine_refresh_endpoint_requires_the_deployment_token(monkeypatch):
    monkeypatch.setattr(api, 'acquire', lambda *_, **__: 'lease')
    monkeypatch.setattr(api, 'tick', lambda **_: {'ok': True, 'refreshed': 0})
    monkeypatch.setenv('TOUCHLINE_DEPLOY_REFRESH_TOKEN', 'test-token')
    with TestClient(api.create_app(setup=False)) as client:
        assert client.post('/api/v1/refresh-engine').status_code == 404
        response = client.post('/api/v1/refresh-engine', headers={'X-Deployment-Refresh-Token': 'test-token'})
    assert response.status_code == 200
    assert response.json() == {'ok': True, 'started': True}


def test_engine_refresh_endpoint_waits_for_the_running_cycle(monkeypatch):
    monkeypatch.setattr(api, 'acquire', lambda *_, **__: None)
    monkeypatch.setenv('TOUCHLINE_DEPLOY_REFRESH_TOKEN', 'test-token')
    with TestClient(api.create_app(setup=False)) as client:
        response = client.post('/api/v1/refresh-engine', headers={'X-Deployment-Refresh-Token': 'test-token'})
    assert response.status_code == 409
