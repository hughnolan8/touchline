"""FotMob's public JSON (unofficial): find a fixture by date + teams, read a confirmed XI."""

import httpx

from touchline.types import Lineup

BASE = "https://www.fotmob.com/api"


class FotMobError(Exception):
    pass


def iter_matches(payload):
    """Yield every {id, home: {name}, away: {name}} object in FotMob's nested daily payload."""
    if isinstance(payload, dict):
        if (
            payload.get("id") is not None
            and isinstance(payload.get("home"), dict)
            and isinstance(payload.get("away"), dict)
        ):
            yield payload
        for value in payload.values():
            yield from iter_matches(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from iter_matches(value)


def _starters(team) -> list[str] | None:
    starters = team.get("starters") if isinstance(team, dict) else None
    if not isinstance(starters, list) or len(starters) != 11:
        return None
    names = []
    for starter in starters:
        player = starter.get("player", starter) if isinstance(starter, dict) else {}
        name = player.get("name") or player.get("fullName")
        if not isinstance(name, str) or not name.strip():
            return None
        names.append(name.strip())
    return names


def parse_lineup(payload: dict) -> Lineup | None:
    """Return the XIs only when FotMob marks the lineup as confirmed."""
    content = payload.get("content", payload) if isinstance(payload, dict) else {}
    lineup = content.get("lineup", content.get("lineups", {})) if isinstance(content, dict) else {}
    if isinstance(lineup, dict) and isinstance(lineup.get("lineup"), dict):
        lineup = lineup["lineup"]
    if not isinstance(lineup, dict) or lineup.get("confirmed") is not True:
        return None
    home = _starters(lineup.get("homeTeam", lineup.get("home", {})))
    away = _starters(lineup.get("awayTeam", lineup.get("away", {})))
    return Lineup(home, away) if home and away else None


class FotMob:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=20, headers={"User-Agent": "Touchline/2.0"})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.client.close()

    def _get(self, path: str, params: dict):
        try:
            response = self.client.get(BASE + path, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise FotMobError(f"FotMob request failed: {type(error).__name__}") from None

    def day(self, date_yyyymmdd: str) -> list[dict]:
        return list(iter_matches(self._get("/matches", {"date": date_yyyymmdd})))

    def lineup(self, match_id) -> Lineup | None:
        return parse_lineup(self._get("/matchDetails", {"matchId": match_id}))
