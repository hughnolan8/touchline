from backend.db import connect
from backend.understat import import_epl_results, sync_epl_seasons


class FakeLeague:
    def get_match_data(self, season, **kwargs):
        assert kwargs['timeout'] == 30
        return [
            {'id': '1', 'isResult': True, 'h': {'title': 'Arsenal'}, 'a': {'title': 'Chelsea'},
             'goals': {'h': '2', 'a': '1'}, 'datetime': '2024-08-16 19:00:00'},
            {'id': '2', 'isResult': False, 'h': {'title': 'Liverpool'}, 'a': {'title': 'Everton'},
             'goals': {'h': None, 'a': None}, 'datetime': '2024-08-17 14:00:00'},
        ]


class FakeClient:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def league(self, league):
        assert league == 'EPL'
        return FakeLeague()


def test_import_epl_results_keeps_completed_scores_only():
    with connect() as connection:
        assert import_epl_results(connection, [2024], client_factory=FakeClient) == 1
        match = connection.execute('SELECT status,stats,kickoff FROM matches').fetchone()
    assert match['status'] == 'finished'
    assert match['stats'] == '{"hg":2,"ag":1}'
    assert match['kickoff'] == '2024-08-16T19:00:00+00:00'


def test_sync_epl_seasons_imports_results_and_scheduled_fixtures():
    with connect() as connection:
        assert sync_epl_seasons(connection, [2024], client_factory=FakeClient, observed='2024-08-18T00:00:00+00:00') == 2
        matches = connection.execute('SELECT source,source_id,status,stats,kickoff FROM matches ORDER BY source_id').fetchall()
        aliases = connection.execute('SELECT source,name FROM aliases ORDER BY name').fetchall()
    assert [dict(match) for match in matches] == [
        {'source': 'understat', 'source_id': '1', 'status': 'finished', 'stats': '{"hg":2,"ag":1}', 'kickoff': '2024-08-16T19:00:00+00:00'},
        {'source': 'understat', 'source_id': '2', 'status': 'scheduled', 'stats': '{}', 'kickoff': '2024-08-17T14:00:00+00:00'},
    ]
    assert {tuple(alias) for alias in aliases} == {('understat', 'Arsenal'), ('understat', 'Chelsea'), ('understat', 'Everton'), ('understat', 'Liverpool')}


class MalformedLeague:
    def get_match_data(self, season, **kwargs):
        assert kwargs['timeout'] == 30
        return [{'id': 'bad', 'isResult': True, 'h': {'title': 'Arsenal'}, 'a': {'title': 'Chelsea'}, 'goals': {'h': 'x', 'a': '1'}, 'datetime': '2024-08-16 19:00:00'}]


class MalformedClient(FakeClient):
    def league(self, league):
        return MalformedLeague()


def test_sync_epl_seasons_quarantines_malformed_records():
    with connect() as connection:
        assert sync_epl_seasons(connection, [2024], client_factory=MalformedClient, observed='2024-08-18T00:00:00+00:00') == 0
        quarantine = connection.execute('SELECT source,reason FROM quarantine').fetchone()
    assert tuple(quarantine) == ('understat', "invalid literal for int() with base 10: 'x'")
