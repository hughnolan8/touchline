"""football-data.co.uk CSVs: season results with full-time scores, and next week's fixtures.

Kick-off times in the CSVs are UK local time. No key; one request per file.
"""

import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from touchline.leagues import BY_CODE
from touchline.types import Fixture

BASE = "https://www.football-data.co.uk"
UK = ZoneInfo("Europe/London")


class FootballDataError(Exception):
    pass


def season_start(at: str) -> int:
    """Start year of the European season containing `at` (seasons start in July)."""
    value = datetime.fromisoformat(at)
    return value.year if value.month >= 7 else value.year - 1


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def _kickoff(date: str, time: str) -> str:
    fmt = "%d/%m/%Y" if len(date.split("/")[-1]) == 4 else "%d/%m/%y"
    day = datetime.strptime(date, fmt)
    hour, minute = (int(x) for x in (time or "15:00").split(":"))
    local = day.replace(hour=hour, minute=minute, tzinfo=UK)
    return local.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")


def parse(text: str, leagues: set[str]) -> tuple[list[Fixture], list[dict]]:
    """Rows for `leagues` -> Fixtures (finished when both full-time goals are present)."""
    fixtures, rejected = [], []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        if row.get("Div") not in leagues or not row.get("HomeTeam"):
            continue
        try:
            finished = bool(row.get("FTHG")) and bool(row.get("FTAG"))
            fixtures.append(
                Fixture(
                    source_id="",
                    league=row["Div"],
                    home=row["HomeTeam"],
                    away=row["AwayTeam"],
                    kickoff=_kickoff(row["Date"], row.get("Time", "")),
                    finished=finished,
                    hg=int(row["FTHG"]) if finished else None,
                    ag=int(row["FTAG"]) if finished else None,
                )
            )
        except (KeyError, TypeError, ValueError):
            rejected.append(row)
    return fixtures, rejected


def _get(path: str, client: httpx.Client | None) -> str:
    own = client is None
    client = client or httpx.Client(
        timeout=30, follow_redirects=True, headers={"User-Agent": "Touchline/2.0"}
    )
    try:
        response = client.get(BASE + path)
        response.raise_for_status()
        return response.content.decode("utf-8-sig", errors="replace")
    except httpx.HTTPError as error:
        raise FootballDataError(f"football-data request failed: {type(error).__name__}") from None
    finally:
        if own:
            client.close()


def fetch_results(league: str, season: int, client: httpx.Client | None = None):
    """One league-season of results (and any listed unplayed fixtures)."""
    return parse(_get(f"/mmz4281/{season_code(season)}/{league}.csv", client), {league})


def fetch_fixtures(client: httpx.Client | None = None):
    """Upcoming fixtures for the next week across all supported leagues."""
    return parse(_get("/fixtures.csv", client), set(BY_CODE))
