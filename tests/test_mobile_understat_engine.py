from backend.mobile import engine
from backend.db import connect
from backend.providers import ingest_match


def test_bootstrap_syncs_active_and_prior_three_understat_seasons(monkeypatch):
    calls = []

    def sync(connection, seasons):
        calls.append(list(seasons))
        return 0

    monkeypatch.setattr(engine, 'sync_epl_seasons', sync)
    assert engine.bootstrap('2026-09-17T12:00:00+00:00') is True
    assert calls == [[2023, 2024, 2025, 2026]]
    assert engine.bootstrap('2026-09-17T12:00:00+00:00') is False


def test_current_season_refresh_uses_understat(monkeypatch):
    calls = []

    def sync(connection, seasons):
        calls.append(list(seasons))
        return 42

    monkeypatch.setattr(engine, 'sync_epl_seasons', sync)
    assert engine.import_scores('2026-02-01T12:00:00+00:00') == 42
    assert calls == [[2025]]


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
        ingest_match(connection, 'test', 'lineup-window', 'E0', 'Arsenal', 'Chelsea', '2026-09-17T12:30:00+00:00', True, 'scheduled', {})
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
            return 1
        def close(self):
            pass

    monkeypatch.setattr(engine, 'FotMobLineups', Lineups)
    monkeypatch.setattr(engine, 'MobileOdds', Odds)
    monkeypatch.setattr(engine, 'forecast', lambda *args: {'model': 'Dixon-Coles + confirmed XI', 'probabilities': {}})
    monkeypatch.setattr(engine, 'place_required_bet', lambda *args: 'placed')
    result = engine.tick(at)
    assert result['lineups'] == 1
    assert [call[0] for call in calls] == ['lineups', 'odds']
    with connect() as connection:
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
    monkeypatch.setattr(engine, 'MobileOdds', Odds)
    result = engine.tick(at)
    assert result['refreshed'] == 1
