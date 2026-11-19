from backend.competitions import COMPETITIONS, competition
from backend.odds_api import parse_events


def test_every_supported_league_has_its_understat_and_odds_identifiers():
    assert [(item.code, item.understat, item.odds_sport) for item in COMPETITIONS] == [
        ('E0', 'EPL', 'soccer_epl'),
        ('SP1', 'La_Liga', 'soccer_spain_la_liga'),
        ('D1', 'Bundesliga', 'soccer_germany_bundesliga'),
        ('I1', 'Serie_A', 'soccer_italy_serie_a'),
        ('F1', 'Ligue_1', 'soccer_france_ligue_one'),
    ]


def test_odds_ingestion_rejects_an_event_from_another_competition(monkeypatch):
    monkeypatch.setattr('backend.odds_api.quarantine', lambda *_: None)
    event = {'sport_key': competition('E0').odds_sport, 'commence_time': '2026-09-25T12:00:00Z'}
    assert parse_events(object(), [event], '2026-09-24T12:00:00+00:00', 'SP1') == 0
