"""The five-minute tick: every automated step, in order, each isolated from the others' errors.

Per fixture (minutes before kickoff, from the league's Strategy):
  entry_minutes..decide_cutoff  refresh odds once, store the entry price and decide with the
                                baseline model (no confirmed-XI requirement); fixtures still
                                unpriced in the last two ticks before the cutoff get Betfair
  decide_cutoff..0              record "missed" if no decision was possible
  close_minutes..0              refresh odds and store the closing line for placed bets
  after full time               settle once football-data reports the score
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from touchline import strategy
from touchline.config import config
from touchline.db import connect, get_setting, job_run, minutes_until, now, rows
from touchline.jobs import ingest, ledger, modelling, odds
from touchline.leagues import LEAGUES
from touchline.sources import betfair, football_data, fotmob, odds_api, understat

log = logging.getLogger(__name__)
_lock = threading.Lock()
ROSTERS_PER_TICK = 25
REFIT_HOURS = 12
SYNC_HOURS = 6


@dataclass
class Sources:
    """Injectable source functions so tests run the real tick with fakes."""

    fetch_results: object = football_data.fetch_results
    fetch_fixtures: object = football_data.fetch_fixtures
    fetch_roster: object = understat.fetch_roster
    fetch_odds: object = odds_api.fetch
    fetch_betfair: object = betfair.fetch
    fotmob: object = fotmob.FotMob
    errors: list = field(default_factory=list)


def _older(stamp: str | None, at: str, hours: float) -> bool:
    return not stamp or datetime.fromisoformat(stamp) < datetime.fromisoformat(at) - timedelta(
        hours=hours
    )


def _step(src: Sources, name: str, fn, *args):
    try:
        return fn(*args)
    except Exception as error:  # one failing provider must not stop the ledger
        log.warning("%s failed: %s", name, error)
        src.errors.append(f"{name}: {type(error).__name__}: {error}"[:300])
        return None


def _sync(src: Sources, at: str) -> int:
    """Results per league every SYNC_HOURS (every 30 min while a fixture is overdue)."""
    season = football_data.season_start(at)
    overdue_cutoff = (datetime.fromisoformat(at) - timedelta(hours=2)).isoformat()
    total = 0
    with connect() as conn:
        fixtures_synced = get_setting(conn, "synced:fixtures")
    if _older(fixtures_synced, at, SYNC_HOURS):
        total += _step(src, "fixtures", ingest.sync_fixtures, at, src.fetch_fixtures) or 0
    for lg in LEAGUES:
        with connect() as conn:
            last = get_setting(conn, f"synced:{lg.code}")
            overdue = conn.execute(
                "SELECT 1 FROM matches WHERE league=? AND status='scheduled' AND kickoff<?",
                (lg.code, overdue_cutoff),
            ).fetchone()
        if _older(last, at, SYNC_HOURS) or (overdue and _older(last, at, 0.5)):
            synced = _step(
                src,
                f"results {lg.code}",
                ingest.sync_results,
                lg.code,
                [season],
                at,
                src.fetch_results,
            )
            total += synced or 0
    return total


def _fit(src: Sources, at: str) -> int:
    fitted = 0
    for lg in LEAGUES:
        with connect() as conn:
            model = modelling.latest_model(conn, lg.code, "baseline-v1")
        if _older(model and model["created_at"], at, REFIT_HOURS):
            fitted += bool(_step(src, f"fit {lg.code}", modelling.fit_league, lg.code, at))
    return fitted


def _refresh_odds(src: Sources, leagues: set, at: str, max_age_hours: float) -> None:
    if not config().odds_api_key:
        return
    with connect() as conn:
        due = {
            lg
            for lg in leagues
            if _older(get_setting(conn, f"odds_refreshed:{lg}"), at, max_age_hours)
        }
    if due:
        _step(src, "odds", odds.refresh_odds, due, at, src.fetch_odds)


def _windows(at: str) -> list[tuple[dict, float, strategy.Strategy]]:
    with connect() as conn:
        matches = rows(
            conn,
            "SELECT * FROM matches WHERE status='scheduled' AND kickoff>? AND kickoff<=?",
            (at, (datetime.fromisoformat(at) + timedelta(hours=4)).isoformat()),
        )
        return [
            (m, minutes_until(m["kickoff"], at), strategy.load(conn, m["league"])) for m in matches
        ]


def run(at: str, src: Sources) -> dict:
    summary = {"synced": _sync(src, at)}
    summary["rosters"] = _step(
        src, "rosters", ingest.hydrate_rosters, ROSTERS_PER_TICK, src.fetch_roster
    )
    summary["fitted"] = _fit(src, at)
    summary["predicted"] = _step(src, "predict", modelling.predict_upcoming, at)
    # All leagues, even with no known fixtures: this also supplies fixtures if Understat is down.
    _refresh_odds(src, {lg.code for lg in LEAGUES}, at, config().odds_refresh_hours)

    windows = _windows(at)
    entry = [(m, s) for m, mins, s in windows if s.decide_cutoff < mins <= s.entry_minutes]
    with connect() as conn:
        need_entry = [
            (m, s) for m, s in entry if not ledger.stored_snapshot(conn, m["id"], "entry")
        ]
    # Entry refreshes follow the credit plan: shared per league slot, biggest slots first.
    if need_entry and config().odds_api_key and (due := odds.entry_due(at)):
        _step(src, "odds", odds.refresh_odds, due, at, src.fetch_odds)
    if need_entry and config().betfair_app_key and (late := odds.betfair_due(need_entry, at)):
        _step(src, "betfair", odds.refresh_betfair, late, at, src.fetch_betfair)
    with connect() as conn:
        summary["entries"] = sum(
            bool(ledger.snapshot(conn, m["id"], "entry", at, s.max_quote_age))
            for m, s in need_entry
        )

    decisions = []
    with connect() as conn:
        for m, _ in entry:
            decided = conn.execute("SELECT 1 FROM decisions WHERE match_id=?", (m["id"],))
            if ledger.stored_snapshot(conn, m["id"], "entry") and not decided.fetchone():
                decisions.append(ledger.decide(conn, m, None, at))
    with connect() as conn:
        for m, mins, s in windows:
            if 0 < mins <= s.decide_cutoff and (result := ledger.missed(conn, m, at)):
                decisions.append(result)
    summary["decisions"] = decisions

    closing = [(m, s) for m, mins, s in windows if 0 < mins <= s.close_minutes]
    with connect() as conn:
        bets = {
            b["match_id"]: b
            for b in rows(conn, "SELECT * FROM bets WHERE status='open' AND close_odds IS NULL")
        }
    closing = [(m, s) for m, s in closing if m["id"] in bets]
    if config().odds_closing_refresh:
        _refresh_odds(src, {m["league"] for m, _ in closing}, at, 2 / 60)
    with connect() as conn:
        summary["closed"] = sum(
            ledger.close(conn, bets[m["id"]], at, s.max_quote_age) for m, s in closing
        )
        summary["settled"] = ledger.settle(conn, at)
    if src.errors:
        summary["errors"] = src.errors
    return summary


def tick(at: str | None = None, src: Sources | None = None) -> dict:
    """Run one cycle. Overlapping calls are skipped rather than queued."""
    if not _lock.acquire(blocking=False):
        return {"skipped": True}
    try:
        with job_run("tick") as summary:
            summary.update(run(at or now(), src or Sources()))
            log.info("tick %s", {k: v for k, v in summary.items() if k != "decisions"})
            return summary
    finally:
        _lock.release()
