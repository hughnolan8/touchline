"""Environment settings, read on every call so tests can monkeypatch the environment."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    db_path: Path
    odds_api_key: str | None
    odds_max_requests_per_day: int | None
    odds_refresh_hours: float
    odds_closing_refresh: bool
    pushover_token: str | None
    pushover_user: str | None
    pushover_device: str | None
    dashboard_url: str | None
    admin_token: str | None
    scheduler: bool
    tick_seconds: int


def _int(name: str) -> int | None:
    value = os.environ.get(name)
    return int(value) if value else None


def config() -> Config:
    env = os.environ.get
    return Config(
        db_path=Path(env("TOUCHLINE_DB", "data/touchline.sqlite3")),
        odds_api_key=env("ODDS_API_KEY"),
        odds_max_requests_per_day=_int("ODDS_MAX_REQUESTS_PER_DAY"),
        odds_refresh_hours=float(env("ODDS_REFRESH_HOURS", "24")),
        odds_closing_refresh=env("ODDS_CLOSING_REFRESH", "1") == "1",
        pushover_token=env("PUSHOVER_APP_TOKEN"),
        pushover_user=env("PUSHOVER_USER_KEY"),
        pushover_device=env("PUSHOVER_DEVICE"),
        dashboard_url=env("DASHBOARD_URL"),
        admin_token=env("TOUCHLINE_ADMIN_TOKEN"),
        scheduler=env("TOUCHLINE_SCHEDULER", "1") == "1",
        tick_seconds=int(env("TOUCHLINE_TICK_SECONDS", "300")),
    )


def setup_logging() -> None:
    """One-line logs. httpx is quietened because its URLs carry the Odds API key."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
