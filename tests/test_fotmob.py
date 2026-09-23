from backend.app.fotmob import FotMobLineups


def test_fotmob_lineup_parser_requires_confirmed_complete_elevens():
    players = lambda prefix: [{'player': {'id': f'{prefix}{index}', 'name': f'{prefix} Player {index}'}} for index in range(11)]
    payload = {'content': {'lineup': {'confirmed': True, 'homeTeam': {'starters': players('home')}, 'awayTeam': {'starters': players('away')}}}}
    lineups = FotMobLineups._lineups(payload)
    assert len(lineups['home']) == len(lineups['away']) == 11
    assert lineups['home'][0] == {'id': 'home0', 'name': 'home Player 0', 'source': 'fotmob'}
    payload['content']['lineup']['confirmed'] = False
    assert FotMobLineups._lineups(payload) is None


def test_fotmob_fixture_parser_handles_nested_daily_matches():
    payload = {'leagues': [{'matches': [{'id': 123, 'home': {'name': 'Arsenal'}, 'away': {'name': 'Chelsea'}}]}]}
    fixtures = list(FotMobLineups._fixtures(payload))
    assert fixtures == [{'id': 123, 'home': {'name': 'Arsenal'}, 'away': {'name': 'Chelsea'}}]
