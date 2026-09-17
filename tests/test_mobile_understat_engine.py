from backend.mobile import engine


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
