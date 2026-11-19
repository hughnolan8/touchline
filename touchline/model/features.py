"""Leak-free confirmed-XI features built from in-memory results and player stats. Pure.

Every feature for a fixture uses only data with kickoff strictly before the cutoff.
"""

import math
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime
from itertools import accumulate

from touchline.teams import norm

HALF_LIFE_DAYS = 180
PRIOR_MINUTES = 540
NO_HISTORY = {"rest_days": 7.0, "congestion": 0.0, "attack_form": 0.0, "defence_form": 0.0}


def _days(a: str, b: str) -> float:
    return (datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds() / 86400


class FeatureBuilder:
    """Index one league's results (`{id, home, away, kickoff, hg, ag}`) and player stats
    (`{match_id, player_id, name, team_id, starter, minutes, xg, xa, kickoff}`)."""

    def __init__(self, results: list[dict], stats: list[dict]):
        self.games = defaultdict(list)  # team -> [(kickoff, scored, conceded)]
        for r in sorted(results, key=lambda r: r["kickoff"]):
            self.games[r["home"]].append((r["kickoff"], r["hg"], r["ag"]))
            self.games[r["away"]].append((r["kickoff"], r["ag"], r["hg"]))
        self.players = defaultdict(list)  # player -> [(kickoff, minutes, xg, xa)]
        self.starters = defaultdict(lambda: defaultdict(list))  # match -> team -> [player]
        names = defaultdict(lambda: defaultdict(set))  # team -> norm(name) -> {player}
        for s in sorted(stats, key=lambda s: s["kickoff"]):
            self.players[s["player_id"]].append((s["kickoff"], s["minutes"], s["xg"], s["xa"]))
            names[s["team_id"]][norm(s["name"])].add(s["player_id"])
            if s["starter"]:
                self.starters[s["match_id"]][s["team_id"]].append(s["player_id"])
        self.names = {
            team: {k: next(iter(v)) for k, v in by.items() if len(v) == 1}
            for team, by in names.items()
        }
        ordered = sorted((s["kickoff"], s["minutes"], s["xg"], s["xa"]) for s in stats)
        self._kickoffs = [row[0] for row in ordered]
        self._cum = [list(accumulate(row[i] for row in ordered)) for i in (1, 2, 3)]

    def baseline(self, cutoff: str) -> tuple[float, float]:
        """League-average xG90/xA90 from appearances before the cutoff."""
        i = bisect_left(self._kickoffs, cutoff)
        if not i or not self._cum[0][i - 1]:
            return 0.0, 0.0
        minutes, xg, xa = (c[i - 1] for c in self._cum)
        return xg / minutes * 90, xa / minutes * 90

    def player_rate(self, player_id: str | None, cutoff: str, base: tuple[float, float]):
        """Decayed xG90/xA90 shrunk toward the league baseline; unknown players = baseline."""
        minutes = xg = xa = 0.0
        for kickoff, mins, pxg, pxa in self.players.get(player_id, ()):
            if kickoff >= cutoff:
                break
            weight = math.exp(-math.log(2) * _days(cutoff, kickoff) / HALF_LIFE_DAYS)
            minutes += weight * mins
            xg += weight * pxg
            xa += weight * pxa
        strength = minutes / (minutes + PRIOR_MINUTES)
        own_xg = xg / minutes * 90 if minutes else 0.0
        own_xa = xa / minutes * 90 if minutes else 0.0
        return (
            strength * own_xg + (1 - strength) * base[0],
            strength * own_xa + (1 - strength) * base[1],
        )

    def team_context(self, team: str, cutoff: str) -> dict:
        games = self.games.get(team, [])
        recent = games[: bisect_left(games, (cutoff,))][-5:]
        if not recent:
            return dict(NO_HISTORY)
        return {
            "rest_days": max(0.0, min(21.0, _days(cutoff, recent[-1][0]))),
            "congestion": float(sum(_days(cutoff, g[0]) <= 14 for g in recent)),
            "attack_form": sum(g[1] for g in recent) / len(recent),
            "defence_form": sum(g[2] for g in recent) / len(recent),
        }

    def side(self, team: str, players: list[str | None], cutoff: str) -> dict:
        base = self.baseline(cutoff)
        rates = [self.player_rate(p, cutoff, base) for p in players]
        return {
            "xg90": sum(r[0] for r in rates),
            "xa90": sum(r[1] for r in rates),
            **self.team_context(team, cutoff),
        }

    def resolve(self, team: str, names: list[str]) -> list[str | None]:
        """Map lineup names (e.g. FotMob) to Understat player ids by exact normalised name."""
        known = self.names.get(team, {})
        return [known.get(norm(name)) for name in names]

    def for_lineup(self, home: str, away: str, lineup: dict, cutoff: str) -> dict:
        return {
            "home": self.side(home, self.resolve(home, lineup["home"]), cutoff),
            "away": self.side(away, self.resolve(away, lineup["away"]), cutoff),
        }

    def historical(self, match: dict) -> dict | None:
        """Features from the actual starting XIs of a completed match, or None if incomplete."""
        starters = self.starters.get(match["id"], {})
        home, away = starters.get(match["home"], []), starters.get(match["away"], [])
        if len(home) != 11 or len(away) != 11:
            return None
        return {
            "home": self.side(match["home"], home, match["kickoff"]),
            "away": self.side(match["away"], away, match["kickoff"]),
        }
