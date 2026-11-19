"""Understat via understatapi: per-match player rosters (xG/xA) for the XI model.

As of Nov 2026 Understat's AJAX API returns HTML errors, so rosters are unavailable.
"""

from understatapi import UnderstatClient

from touchline.types import PlayerStat

TIMEOUT = 30


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


def fetch_roster(match_source_id: str, client_factory=UnderstatClient) -> dict:
    with client_factory() as client:
        return client.match(match=match_source_id).get_roster_data(timeout=TIMEOUT)
