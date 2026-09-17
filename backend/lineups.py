"""Confirmed Premier League lineups from API-Football."""
import os
from datetime import datetime
import httpx

from .db import dump, now
from .providers import canonical

SOURCE = 'api-football'
BASE_URL = 'https://v3.football.api-sports.io'

class LineupError(RuntimeError): pass

class ApiFootball:
    def __init__(self, client=None): self.client = client or httpx.Client(timeout=20)
    def close(self): self.client.close()
    def _get(self, path, params):
        key = os.environ.get('API_FOOTBALL_KEY')
        if not key: raise LineupError('API_FOOTBALL_KEY is not configured')
        try:
            response = self.client.get(BASE_URL + path, params=params, headers={'x-apisports-key': key}); response.raise_for_status()
            payload = response.json()
            if payload.get('errors'): raise LineupError(str(payload['errors']))
            return payload.get('response', [])
        except (httpx.HTTPError, ValueError) as error: raise LineupError('API-Football request failed') from error
    def confirmed(self, c, match):
        kickoff = datetime.fromisoformat(match['kickoff'])
        fixtures = self._get('/fixtures', {'league': 39, 'season': kickoff.year if kickoff.month >= 7 else kickoff.year - 1, 'date': kickoff.date().isoformat()})
        wanted = None
        for fixture in fixtures:
            try:
                home = canonical(c, SOURCE, fixture['teams']['home']['name']); away = canonical(c, SOURCE, fixture['teams']['away']['name'])
                if home == match['home'] and away == match['away'] and abs(datetime.fromisoformat(fixture['fixture']['date']) - kickoff).total_seconds() < 7200: wanted = fixture['fixture']['id']; break
            except (KeyError, TypeError, ValueError): continue
        if not wanted: return None
        response = self._get('/fixtures/lineups', {'fixture': wanted})
        if len(response) != 2: return None
        parsed = {}
        for item in response:
            team = canonical(c, SOURCE, item['team']['name'])
            side = 'home' if team == match['home'] else 'away' if team == match['away'] else None
            starters = [x.get('player', x) for x in item.get('startXI', [])]
            if not side or len(starters) != 11: return None
            parsed[side] = [{'id': str(x.get('id', '')), 'name': x.get('name', '')} for x in starters]
        if set(parsed) != {'home', 'away'}: return None
        captured = now(); c.execute('INSERT OR IGNORE INTO lineup_snapshots(match_id,source,source_fixture_id,captured_at,payload) VALUES(?,?,?,?,?)', (match['id'], SOURCE, str(wanted), captured, dump(parsed)))
        return {'captured_at': captured, 'fixture_id': str(wanted), 'lineups': parsed}
