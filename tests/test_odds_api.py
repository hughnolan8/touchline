from backend import odds_api


def test_parse_events_ingests_supported_verified_1x2_prices(monkeypatch):
    ingested = []
    quotes = []
    monkeypatch.setattr(odds_api, 'ingest_match', lambda *args: ingested.append(args) or 'match-1')
    monkeypatch.setattr(odds_api, 'add_quote', lambda *args: quotes.append(args))
    observed = '2026-09-24T12:00:00+00:00'
    event = {
        'id': 'fixture-1', 'sport_key': odds_api.SPORT, 'home_team': 'Arsenal', 'away_team': 'Chelsea',
        'commence_time': '2026-09-25T12:00:00Z',
        'bookmakers': [{'key': 'bet365', 'last_update': observed, 'markets': [{'key': 'h2h', 'last_update': observed, 'outcomes': [
            {'name': 'Arsenal', 'price': 2.2}, {'name': 'Draw', 'price': 3.4}, {'name': 'Chelsea', 'price': 3.5},
        ]}]}],
    }
    assert odds_api.parse_events(object(), [event], observed) == 1
    assert ingested[0][1:7] == ('the-odds-api', 'fixture-1', 'E0', 'Arsenal', 'Chelsea', '2026-09-25T12:00:00+00:00')
    assert [(quote[3], quote[6], quote[7]) for quote in quotes] == [('home', 'Bet365', 2.2), ('draw', 'Bet365', 3.4), ('away', 'Bet365', 3.5)]


def test_parse_events_skips_out_of_window_prices_and_quarantines_invalid_events(monkeypatch):
    quarantined = []
    monkeypatch.setattr(odds_api, 'quarantine', lambda *args: quarantined.append(args))
    monkeypatch.setattr(odds_api, 'ingest_match', lambda *_: (_ for _ in ()).throw(AssertionError('must not ingest')))
    observed = '2026-09-24T12:00:00+00:00'
    assert odds_api.parse_events(object(), [
        {'sport_key': odds_api.SPORT, 'commence_time': '2026-10-02T12:00:00Z'},
        {'sport_key': 'soccer_spain_la_liga'},
    ], observed) == 0
    assert len(quarantined) == 1
    assert quarantined[0][1] == 'the-odds-api'
