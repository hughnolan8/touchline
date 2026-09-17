from datetime import datetime, timedelta, timezone

from backend.db import connect, now
from backend.engine import current_model, current_player_model
from backend.playerstats import latest_lineup_snapshot, lineup_features, resolve_player, save_lineup_snapshot, save_roster
from backend.providers import ingest_match


def add_match(c, source_id, when):
    return ingest_match(c, 'understat', source_id, 'E0', 'Arsenal', 'Chelsea', when.isoformat(), True, 'finished', {'hg': 1, 'ag': 0}, now())


def roster(prefix, xg):
    return [{'player_id': f'{prefix}{n}', 'player_name': f'{prefix} player {n}', 'time': 90,
             'starter': True, 'xG': xg, 'xA': xg / 2, 'position': 'F'} for n in range(11)]


def test_roster_is_idempotent_and_lineup_features_exclude_target_and_future():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with connect() as c:
        prior = add_match(c, 'prior', start)
        target = add_match(c, 'target', start + timedelta(days=7))
        future = add_match(c, 'future', start + timedelta(days=14))
        assert save_roster(c, prior, {'h': roster('a', .2), 'a': roster('c', .1)}) == 22
        assert save_roster(c, prior, {'h': roster('a', .2), 'a': roster('c', .1)}) == 22
        save_roster(c, target, {'h': roster('a', 9), 'a': roster('c', 9)})
        save_roster(c, future, {'h': roster('a', 20), 'a': roster('c', 20)})
        xi = [{'id': f'api-{n}', 'name': f'a player {n}'} for n in range(11)]
        features = lineup_features(c, target, 'home', xi, (start + timedelta(days=7)).isoformat())
        assert features and len(features['starters']) == 3
        assert features['xg90'] < 10
        assert c.execute('SELECT COUNT(*) FROM player_match_stats').fetchone()[0] == 66


def test_player_resolution_reuses_exact_team_name_and_rejects_ambiguous_identity():
    with connect() as c:
        team = 'arsenal'
        c.execute('INSERT INTO teams VALUES(?,?)', (team, 'Arsenal'))
        one = resolve_player(c, 'understat', '1', 'Same Name', team)
        c.execute('INSERT INTO players VALUES(?,?)', ('other', 'Same Name'))
        c.execute('INSERT INTO player_aliases VALUES(?,?,?,?,?)', ('other-source', '2', 'Same Name', team, 'other'))
        assert resolve_player(c, 'api-football', '', 'Same Name', team) is None
        assert resolve_player(c, 'api-football', '999', 'Unknown Player', team, create=False) is None
        assert resolve_player(c, 'understat', '1', 'Anything', team) == one


def test_shadow_model_never_replaces_baseline_selection():
    with connect() as c:
        c.execute("INSERT INTO models(competition,created_at,cutoff,samples,payload,metrics) VALUES('E0',?,?,?,?,?)", (now(), now(), 40, '{}', '{\"method\":\"time-decayed Dixon-Coles\"}'))
        c.execute("INSERT INTO models(competition,created_at,cutoff,samples,payload,metrics) VALUES('E0',?,?,?,?,?)", (now(), now(), 40, '{}', '{\"method\":\"Dixon-Coles + confirmed XI\"}'))
        assert current_model(c)['metrics'].find('confirmed XI') == -1
        assert 'confirmed XI' in current_player_model(c)['metrics']


def test_lineup_snapshot_is_timestamped_and_never_available_before_capture():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with connect() as c:
        fixture = add_match(c, 'snapshot', start + timedelta(days=1))
        xi = [{'id': f'a-{n}', 'name': f'A {n}'} for n in range(11)]
        lineups = {'home': xi, 'away': xi}
        captured = (start + timedelta(hours=12)).isoformat()
        assert save_lineup_snapshot(c, fixture, 'test', 'snapshot', lineups, captured)
        assert latest_lineup_snapshot(c, fixture, (start + timedelta(hours=11)).isoformat()) is None
        snapshot = latest_lineup_snapshot(c, fixture, captured)
        assert snapshot['captured_at'] == captured
        assert snapshot['lineups'] == lineups
        assert not save_lineup_snapshot(c, fixture, 'test', 'late', lineups, (start + timedelta(days=2)).isoformat())
