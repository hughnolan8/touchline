"""Understat via understatapi: fixtures, results and per-match player rosters."""

from datetime import UTC, datetime

from understatapi import UnderstatClient

from touchline.leagues import league
from touchline.types import Fixture, PlayerStat

TIMEOUT = 30


def season_start(at: str) -> int:
    """Start year of the European season containing `at` (seasons start in July)."""
    value = datetime.fromisoformat(at)
    return value.year if value.month >= 7 else value.year - 1


def parse_match(raw: dict, league_code: str) -> Fixture:
    finished = bool(raw.get("isResult"))
    kickoff = datetime.strptime(raw["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    goals = raw.get("goals") or {}
    return Fixture(
        source_id=str(raw["id"]),
        league=league_code,
        home=raw["h"]["title"],
        away=raw["a"]["title"],
        kickoff=kickoff.isoformat(timespec="seconds"),
        finished=finished,
        hg=int(goals["h"]) if finished else None,
        ag=int(goals["a"]) if finished else None,
    )


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_roster(raw: dict) -> list[PlayerStat]:
    """Understat roster payload {"h": {...}, "a": {...}} -> player lines."""
    stats = []
    for key, side in (("h", "home"), ("a", "away")):
        roster = raw.get(key, {})
        for item in roster.values() if isinstance(roster, dict) else roster:
            name = item.get("player")
            if not name:
                raise ValueError("Roster row has no player name")
            minutes = _number(item.get("time"))
            # Substitutes are listed with position "Sub" and a non-zero "roster_in".
            starter = (
                minutes > 0
                and item.get("position") != "Sub"
                and str(item.get("roster_in") or "0") == "0"
            )
            stats.append(
                PlayerStat(
                    str(item["player_id"]),
                    name,
                    side,
                    starter,
                    minutes,
                    _number(item.get("xG")),
                    _number(item.get("xA")),
                )
            )
    return stats


def fetch_season(league_code: str, season: int, client_factory=UnderstatClient) -> list[dict]:
    with client_factory() as client:
        endpoint = client.league(league=league(league_code).understat)
        return endpoint.get_match_data(season=str(season), timeout=TIMEOUT)


def fetch_roster(match_source_id: str, client_factory=UnderstatClient) -> dict:
    with client_factory() as client:
        return client.match(match=match_source_id).get_roster_data(timeout=TIMEOUT)
