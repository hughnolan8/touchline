"""Odds API (credit-planned) and Betfair (last chance) -> odds_quotes; also a fixture fallback."""

import logging
import sqlite3
from datetime import datetime, timedelta

from touchline import credits, strategy
from touchline.config import config
from touchline.db import connect, get_setting, minutes_until, quarantine, set_setting
from touchline.jobs import ledger
from touchline.jobs.ingest import find_match, insert_match
from touchline.sources import betfair, odds_api
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
            stored += _store(conn, "odds-api", league, events, rejected, at, horizon)
            set_setting(conn, "odds_api", {"remaining": remaining, "checked_at": at})
            set_setting(conn, f"odds_refreshed:{league}", at)
    log.info("odds leagues=%s events=%s", len(set(leagues)), stored)
    return stored


def refresh_betfair(leagues, at: str, fetch=betfair.fetch) -> int:
    """Last-chance entry prices from the Betfair Exchange (no credits): the scheduler calls this
    for fixtures the Odds API plan has left unpriced just before their decide cutoff."""
    cfg = config()
    creds = (cfg.betfair_app_key, cfg.betfair_username, cfg.betfair_password)
    if not all(creds):
        raise betfair.BetfairError("Betfair credentials are not configured")
    horizon = (datetime.fromisoformat(at) + timedelta(days=7)).isoformat()
    stored = 0
    for league in sorted(set(leagues)):
        events, rejected = fetch(league, *creds, at, horizon)
        with connect() as conn:
            stored += _store(conn, "betfair", league, events, rejected, at, horizon)
            set_setting(conn, f"betfair_refreshed:{league}", at)
    log.info("betfair leagues=%s events=%s", len(set(leagues)), stored)
    return stored


def _store(conn, source: str, league: str, events, rejected, at: str, horizon: str) -> int:
    """Resolve teams, join to fixtures and store quotes. Returns events stored."""
    # Only invent fixtures when the results source has none for this league this week;
    # otherwise an unmatched name is an alias gap and must not create a duplicate.
    fallback = not conn.execute(
        "SELECT 1 FROM matches WHERE league=? AND status='scheduled' AND kickoff>? AND kickoff<=?",
        (league, at, horizon),
    ).fetchone()
    stored = 0
    for raw in rejected:
        quarantine(conn, source, "unparseable event", raw)
    for event in events:
        try:
            home = canonical(conn, source, event.home)
            away = canonical(conn, source, event.away)
        except ValueError as error:
            quarantine(conn, source, str(error), event.__dict__)
            continue
        match_id = find_match(conn, league, home, away, event.kickoff)
        if not match_id and fallback and at < event.kickoff <= horizon and home != away:
            match_id = insert_match(conn, league, home, away, event.kickoff, at)
        if not match_id:
            quarantine(conn, source, "no matching fixture", event.__dict__ | {"quotes": []})
            continue
        conn.executemany(
            "INSERT OR IGNORE INTO odds_quotes VALUES(?,?,?,?,?,?)",
            [(match_id, q.bookmaker, q.selection, q.odds, q.quoted_at, at) for q in event.quotes],
        )
        stored += 1
    return stored


def entry_due(at: str) -> set[str]:
    """Leagues whose planned entry refresh is due now (see `touchline/credits.py`).

    Only fixtures that can still be bet count: scheduled, before their decide cutoff, with a
    forecast from the active model and no entry price or decision yet.
    """
    with connect() as conn:
        windows, waiting = {}, []
        candidates = conn.execute(
            "SELECT m.id, m.league, m.kickoff FROM matches m WHERE m.status='scheduled' "
            "AND m.kickoff>? AND NOT EXISTS (SELECT 1 FROM decisions d WHERE d.match_id=m.id) "
            "AND NOT EXISTS (SELECT 1 FROM market_snapshots s WHERE s.match_id=m.id "
            "AND s.kind='entry')",
            (at,),
        ).fetchall()
        for match_id, league, kickoff in candidates:
            if league not in windows:
                rules = strategy.load(conn, league)
                windows[league] = (rules, credits.Window(rules.entry_minutes, rules.decide_cutoff))
            rules, window = windows[league]
            forecast = conn.execute(
                "SELECT 1 FROM predictions WHERE match_id=? AND version=?",
                (match_id, rules.active_model),
            ).fetchone()
            if forecast and kickoff > credits.shift(at, window.decide_cutoff):
                waiting.append((league, kickoff))
        horizon = conn.execute("SELECT max(kickoff) FROM matches").fetchone()[0] or at
        remaining = (get_setting(conn, "odds_api") or {}).get("remaining")
    plan = credits.slots(waiting, {lg: w for lg, (_, w) in windows.items()}, _margin())
    cfg = config()
    available = credits.budget(
        int(remaining) if remaining is not None else None,
        at,
        horizon,
        credits.next_reset(at, cfg.odds_reset_day),
    )
    return credits.due(plan, available, at)


def betfair_due(need_entry: list, at: str) -> set[str]:
    """Leagues with a fixture still unpriced within two ticks of its decide cutoff."""
    with connect() as conn:
        return {
            m["league"]
            for m, s in need_entry
            if minutes_until(m["kickoff"], at) <= s.decide_cutoff + 2 * _margin() - 1
            and not ledger.snapshot(conn, m["id"], "entry", at, s.max_quote_age)
        }


def _margin() -> float:
    return config().tick_seconds / 60 + 1
