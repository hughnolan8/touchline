"""FotMob confirmed-XI collection for the pre-kickoff engine window."""
from datetime import datetime

import httpx

from backend.db import connect
from backend.playerstats import save_lineup_snapshot
from backend.providers import canonical


class FotMobError(Exception):
    pass


class FotMobLineups:
    """Resolve a scheduled fixture and persist its confirmed FotMob XI."""

    def __init__(self):
        self.client = httpx.Client(timeout=20, headers={'User-Agent': 'Touchline/1.0'})

    def close(self):
        self.client.close()

    def _get(self, path, params):
        try:
            response = self.client.get(f'https://www.fotmob.com/api{path}', params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise FotMobError('FotMob request failed') from error

    @staticmethod
    def _fixtures(payload):
        """Yield match-list objects across FotMob's nested daily payload."""
        if isinstance(payload, dict):
            if payload.get('id') is not None and isinstance(payload.get('home'), dict) and isinstance(payload.get('away'), dict):
                yield payload
            for value in payload.values():
                yield from FotMobLineups._fixtures(value)
        elif isinstance(payload, list):
            for value in payload:
                yield from FotMobLineups._fixtures(value)

    @staticmethod
    def _players(team):
        starters = team.get('starters') if isinstance(team, dict) else None
        if not isinstance(starters, list) or len(starters) != 11:
            return None
        players = []
        for starter in starters:
            player = starter.get('player', starter) if isinstance(starter, dict) else {}
            player_id = player.get('id') or starter.get('id')
            name = player.get('name') or player.get('fullName') or starter.get('name')
            if player_id is None or not isinstance(name, str) or not name.strip():
                return None
            players.append({'id': str(player_id), 'name': name, 'source': 'fotmob'})
        return players

    @classmethod
    def _lineups(cls, payload):
        content = payload.get('content', payload) if isinstance(payload, dict) else {}
        lineup = content.get('lineup', content.get('lineups', {})) if isinstance(content, dict) else {}
        if isinstance(lineup, dict) and isinstance(lineup.get('lineup'), dict):
            lineup = lineup['lineup']
        if not isinstance(lineup, dict) or lineup.get('confirmed') is not True:
            return None
        home = cls._players(lineup.get('homeTeam', lineup.get('home', {})))
        away = cls._players(lineup.get('awayTeam', lineup.get('away', {})))
        return {'home': home, 'away': away} if home and away else None

    def refresh(self, fixtures, at):
        """Return fixture IDs for which FotMob supplied a confirmed, saved XI."""
        captured = []
        for fixture in fixtures:
            kickoff = datetime.fromisoformat(fixture['kickoff'])
            daily = self._get('/matches', {'date': kickoff.strftime('%Y%m%d')})
            match_id = None
            with connect() as c:
                for candidate in self._fixtures(daily):
                    try:
                        home = canonical(c, 'fotmob', candidate['home']['name'])
                        away = canonical(c, 'fotmob', candidate['away']['name'])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if home == fixture['home'] and away == fixture['away']:
                        match_id = candidate['id']
                        break
            if match_id is None:
                continue
            lineups = self._lineups(self._get('/matchDetails', {'matchId': match_id}))
            if not lineups:
                continue
            with connect() as c:
                if save_lineup_snapshot(c, fixture['id'], 'fotmob', match_id, lineups, at):
                    captured.append(fixture['id'])
        return captured
