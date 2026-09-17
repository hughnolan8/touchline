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
