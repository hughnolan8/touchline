"""Odds API credit planning: spend the monthly budget on the entry refreshes that price most
bettable fixtures. Pure: callers pass fixtures, windows and the credits remaining.

One request prices a whole league, so fixtures of a league whose entry windows overlap share a
"slot": one refresh, timed for when the slot's last fixture enters its window, prices them all.
When credits cannot cover every known slot, the biggest slots win (earliest first on ties).
Part of the budget is held back for days whose fixtures are not published yet.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Window:
    entry_minutes: int
    decide_cutoff: int


@dataclass(frozen=True)
class Slot:
    league: str
    kickoffs: tuple[str, ...]
    refresh_at: str  # first moment one refresh covers every fixture in the slot

    @property
    def size(self) -> int:
        return len(self.kickoffs)


def shift(stamp: str, minutes: float) -> str:
    return (datetime.fromisoformat(stamp) + timedelta(minutes=minutes)).isoformat()


def slots(fixtures: list[tuple[str, str]], windows: dict, margin: float) -> list[Slot]:
    """Group (league, kickoff) fixtures still waiting for an entry price into shared refreshes.

    `margin` (minutes) keeps the slot's first fixture inside its window for at least one more
    tick after the planned refresh time.
    """
    out = []
    for league in sorted({lg for lg, _ in fixtures}):
        w = windows[league]
        span = w.entry_minutes - w.decide_cutoff - margin
        kickoffs = sorted(k for lg, k in fixtures if lg == league)
        while kickoffs:
            first = kickoffs[0]
            group = tuple(k for k in kickoffs if k <= shift(first, max(span, 0)))
            out.append(Slot(league, group, shift(group[-1], -w.entry_minutes)))
            kickoffs = kickoffs[len(group) :]
    return out


def budget(remaining: int | None, at: str, horizon: str, reset_at: str) -> float:
    """Credits to spend on known fixtures, holding back a share for unpublished days."""
    if remaining is None:
        return math.inf
    now, end = datetime.fromisoformat(at), datetime.fromisoformat(reset_at)
    days_left = max((end - now).total_seconds() / 86400, 1e-9)
    unseen = max((end - max(datetime.fromisoformat(horizon), now)).total_seconds() / 86400, 0)
    return max(remaining - round(remaining * min(unseen / days_left, 1)), 0)


def chosen(all_slots: list[Slot], credits: float) -> list[Slot]:
    """The slots worth a credit: biggest first, earliest on ties."""
    ranked = sorted(all_slots, key=lambda s: (-s.size, s.kickoffs[0], s.league))
    return ranked if credits == math.inf else ranked[: int(credits)]


def due(all_slots: list[Slot], credits: float, at: str) -> set[str]:
    """Leagues to refresh now: chosen slots whose refresh time has come."""
    return {s.league for s in chosen(all_slots, credits) if s.refresh_at <= at}


def next_reset(at: str, reset_day: int) -> str:
    """The next monthly credit reset (00:00 UTC on `reset_day`, clamped to the month's end)."""
    now = datetime.fromisoformat(at)
    year, month = now.year, now.month
    for _ in range(2):
        last = (datetime(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
        reset = now.replace(
            month=month,
            year=year,
            day=min(reset_day, last),
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        if reset > now:
            return reset.isoformat()
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    raise AssertionError("unreachable")
