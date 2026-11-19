"""The Odds API -> odds_quotes, under the daily credit cap. Also a fixture fallback."""

import logging
import sqlite3
from datetime import datetime, timedelta

from touchline.config import config
from touchline.db import connect, get_setting, quarantine, set_setting
from touchline.jobs.ingest import find_match, insert_match
from touchline.sources import odds_api
from touchline.teams import canonical

log = logging.getLogger(__name__)


def _reserve_odds_request(conn: sqlite3.Connection, at: str) -> None:
    cap = config().odds_max_requests_per_day
    if cap is None:
        return
    key = f"odds_requests:{at[:10]}"
    used = get_setting(conn, key, 0)
    if used >= cap:
        raise odds_api.OddsApiError(f"daily Odds API cap reached ({cap})")
    set_setting(conn, key, used + 1)


def refresh_odds(leagues, at: str, fetch=odds_api.fetch) -> int:
    """Fetch current 1X2 prices for each league (1 credit each) and store quotes.

    An event with no matching fixture within the next 7 days becomes a scheduled fixture, so
    betting continues when Understat is down; Understat adopts it once it recovers.
    """
    horizon = (datetime.fromisoformat(at) + timedelta(days=7)).isoformat()
    key = config().odds_api_key
    if not key:
        raise odds_api.OddsApiError("ODDS_API_KEY is not configured")
    stored = 0
    for league in sorted(set(leagues)):
        with connect() as conn:
            _reserve_odds_request(conn, at)
        events, rejected, remaining = fetch(league, key)
        with connect() as conn:
            # Only invent fixtures when the results source has none for this league this week;
            # otherwise an unmatched name is an alias gap and must not create a duplicate.
            fallback = not conn.execute(
                "SELECT 1 FROM matches WHERE league=? AND status='scheduled' AND kickoff>? "
                "AND kickoff<=?",
                (league, at, horizon),
            ).fetchone()
            for raw in rejected:
                quarantine(conn, "odds-api", "unparseable event", raw)
            for event in events:
                try:
                    home = canonical(conn, "odds-api", event.home)
                    away = canonical(conn, "odds-api", event.away)
                except ValueError as error:
                    quarantine(conn, "odds-api", str(error), event.__dict__)
                    continue
                match_id = find_match(conn, league, home, away, event.kickoff)
                if not match_id and fallback and at < event.kickoff <= horizon and home != away:
                    match_id = insert_match(conn, league, home, away, event.kickoff, at)
                if not match_id:
                    quarantine(
                        conn, "odds-api", "no matching fixture", event.__dict__ | {"quotes": []}
                    )
                    continue
                conn.executemany(
                    "INSERT OR IGNORE INTO odds_quotes VALUES(?,?,?,?,?,?)",
                    [
                        (match_id, q.bookmaker, q.selection, q.odds, q.quoted_at, at)
                        for q in event.quotes
                    ],
                )
                stored += 1
            set_setting(conn, "odds_api", {"remaining": remaining, "checked_at": at})
            set_setting(conn, f"odds_refreshed:{league}", at)
    log.info("odds leagues=%s events=%s", len(set(leagues)), stored)
    return stored
