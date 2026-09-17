from datetime import datetime, timedelta, timezone

from backend.backtest import summary, walk_forward, walk_forward_player
from backend.playerstats import save_roster
from backend.db import connect, dump, now
from backend.providers import ingest_match


def add_result(connection, number, home, away, home_goals, away_goals):
    # Keep repeat fixtures more than the provider's two-day identity window apart.
    kickoff = (datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=number * 3)).isoformat()
    ingest_match(connection, 'test', str(number), 'E0', home, away, kickoff, True, 'finished',
                 {'hg': home_goals, 'ag': away_goals}, now())


def test_walk_forward_uses_only_prior_results_and_reports_probability_metrics():
    with connect() as connection:
        for number in range(40):
            add_result(connection, number, 'Arsenal', 'Chelsea', number % 3, (number + 1) % 2)
        add_result(connection, 41, 'Arsenal', 'Chelsea', 2, 1)
        evaluations = walk_forward(connection)
    assert len(evaluations) == 1
    assert evaluations[0]['id']
    assert set(evaluations[0]['probabilities']) == {'home', 'draw', 'away'}
    assert abs(sum(evaluations[0]['probabilities'].values()) - 1) < 1e-9
    report = summary(evaluations)
    assert report['fixtures'] == 1
    assert 0 <= report['accuracy'] <= 1
    assert report['log_loss'] >= 0
    assert 0 <= report['brier_score'] <= 1


def test_backtest_summary_handles_no_eligible_fixtures():
    assert summary([])['fixtures'] == 0


def test_walk_forward_reuses_models_for_simultaneous_fixtures(monkeypatch):
    with connect() as connection:
        for number in range(40):
            add_result(connection, number, 'Arsenal', 'Chelsea', number % 3, (number + 1) % 2)
        kickoff = (datetime(2025, 1, 1, tzinfo=timezone.utc)).isoformat()
        ingest_match(connection, 'test', 'simultaneous-one', 'E0', 'Arsenal', 'Chelsea', kickoff, True, 'finished', {'hg': 1, 'ag': 0}, now())
        ingest_match(connection, 'test', 'simultaneous-two', 'E0', 'Chelsea', 'Arsenal', kickoff, True, 'finished', {'hg': 0, 'ag': 1}, now())
        evaluations = walk_forward(connection)
    assert len(evaluations) == 2


def test_player_walk_forward_uses_only_prior_match_player_stats():
    def roster(prefix, xg):
        return [{'player_id': f'{prefix}{n}', 'player_name': f'{prefix} player {n}', 'time': 90,
                 'starter': True, 'xG': xg, 'xA': xg / 2, 'position': 'F'} for n in range(11)]
    with connect() as connection:
        for number in range(41):
            add_result(connection, number, 'Arsenal', 'Chelsea', number % 3, (number + 1) % 2)
            match = connection.execute('SELECT id FROM matches WHERE source_id=?', (str(number),)).fetchone()[0]
            save_roster(connection, match, {'h': roster('a', .2), 'a': roster('c', .1)})
        evaluations = walk_forward_player(connection)
    assert len(evaluations) == 1
    assert set(evaluations[0]['probabilities']) == {'home', 'draw', 'away'}
