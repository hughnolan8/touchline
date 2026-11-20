"""Paper-betting strategy settings. One dataclass; per-league overrides live in settings."""

import sqlite3
from dataclasses import asdict, dataclass, fields

from touchline.db import get_setting, set_setting

MODEL_VERSIONS = ("baseline-v1", "xi-v2")


@dataclass(frozen=True)
class Strategy:
    enabled: bool = True
    active_model: str = "baseline-v1"
    stake_mode: str = "kelly"  # kelly | flat
    flat_stake: float = 10.0
    kelly_fraction: float = 0.25
    max_bet_fraction: float = 0.02  # cap per bet as a share of bankroll
    min_stake: float = 1.0
    min_edge: float = 0.05
    max_exposure: float = 0.10  # cap on open stakes as a share of bankroll
    max_quote_age: int = 15  # minutes
    entry_minutes: int = 60  # capture the entry price from this many minutes out
    decide_cutoff: int = 30  # record 'missed' if undecided this many minutes out
    close_minutes: int = 5  # capture the closing line inside this window

    def __post_init__(self):
        checks = {
            "active_model": self.active_model in MODEL_VERSIONS,
            "stake_mode": self.stake_mode in ("kelly", "flat"),
            "kelly_fraction": 0 < self.kelly_fraction <= 1,
            "max_bet_fraction": 0 < self.max_bet_fraction <= 0.10,
            "min_stake": 0.01 <= self.min_stake <= 100,
            "flat_stake": 0 < self.flat_stake <= 1000,
            "min_edge": 0 <= self.min_edge <= 1,
            "max_exposure": 0 < self.max_exposure <= 1,
            "max_quote_age": 1 <= self.max_quote_age <= 60,
            "windows": 0 < self.close_minutes < self.decide_cutoff < self.entry_minutes <= 240,
        }
        bad = [name for name, ok in checks.items() if not ok]
        if bad:
            raise ValueError(f"Invalid strategy settings: {', '.join(bad)}")


def load(conn: sqlite3.Connection, league: str) -> Strategy:
    known = {f.name for f in fields(Strategy)}
    stored = get_setting(conn, f"strategy:{league}", {})
    return Strategy(**{k: v for k, v in stored.items() if k in known})


def save(conn: sqlite3.Connection, league: str, **changes) -> Strategy:
    strategy = Strategy(**{**asdict(load(conn, league)), **changes})
    set_setting(conn, f"strategy:{league}", asdict(strategy))
    return strategy
