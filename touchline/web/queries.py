"""Read-only queries behind each page. Each returns plain dicts for the templates."""

import json
import sqlite3

from touchline import accumulator, betting
from touchline.db import get_setting, rows
from touchline.jobs.ledger import stored_snapshot
from touchline.jobs.modelling import latest_model, upcoming
from touchline.leagues import LEAGUES

_MATCH = (
    "SELECT m.*, h.name home_name, a.name away_name FROM matches m "
    "JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away"
)
_BETS = (
    "SELECT b.*, m.league, m.kickoff, h.name home_name, a.name away_name FROM bets b "
    "JOIN matches m ON m.id=b.match_id JOIN teams h ON h.id=m.home "
    "JOIN teams a ON a.id=m.away"
)


def bets(conn: sqlite3.Connection, league: str | None, limit: int = 200) -> list[dict]:
    where, args = (" WHERE m.league=?", [league]) if league else ("", [])
    return rows(conn, _BETS + where + " ORDER BY b.created_at DESC LIMIT ?", [*args, limit])


def overview(conn: sqlite3.Connection, league: str | None) -> dict:
    """Bankroll is shared across leagues, so the account always covers every bet."""
    return {
        "account": betting.account(rows(conn, "SELECT * FROM bets")),
        "recent": bets(conn, league, 8),
    }


def _best_prices(conn: sqlite3.Connection, match_id: str) -> dict:
    entry = stored_snapshot(conn, match_id, "entry")
    if entry:
        return {s: {"odds": p.odds, "bookmaker": p.bookmaker} for s, p in entry.items()}
    best = rows(
        conn,
        "SELECT selection, MAX(odds) odds, bookmaker FROM odds_quotes q WHERE "
        "match_id=? AND quoted_at=(SELECT MAX(quoted_at) FROM odds_quotes WHERE "
        "match_id=q.match_id AND bookmaker=q.bookmaker) GROUP BY selection",
        (match_id,),
    )
    return {r["selection"]: r for r in best}


def predictions(conn: sqlite3.Connection, league: str | None, at: str) -> list[dict]:
    out = []
    for m in upcoming(conn, at, league):
        match = dict(conn.execute(_MATCH + " WHERE m.id=?", (m["id"],)).fetchone())
        p = conn.execute(
            "SELECT * FROM predictions WHERE match_id=? ORDER BY with_lineup DESC, id DESC LIMIT 1",
            (m["id"],),
        ).fetchone()
        prices = _best_prices(conn, m["id"])
        probs = {s: p[s] for s in ("home", "draw", "away")} if p else None
        edges = {s: betting.edge(probs[s], prices[s]["odds"]) for s in prices} if probs else {}
        decision = conn.execute(
            "SELECT action, reason FROM decisions WHERE match_id=?", (m["id"],)
        ).fetchone()
        out.append(
            {
                **match,
                "probs": probs,
                "prices": prices,
                "edges": edges,
                "version": p["version"] if p else None,
                "pick": max(edges, key=edges.get) if edges else None,
                "decision": dict(decision) if decision else None,
            }
        )
    return out


def accumulator_builder(
    conn: sqlite3.Connection, league: str | None, at: str, chosen: dict[str, str], stake: float
) -> dict:
    """Upcoming priced fixtures plus the accumulator built from `{match_id: selection}`."""
    fixtures = [f for f in predictions(conn, league, at) if accumulator.candidates(f)]
    legs = accumulator.pick(fixtures, chosen)
    return {
        "fixtures": fixtures,
        "chosen": {leg["match_id"]: leg["selection"] for leg in legs},
        "acca": accumulator.combine(legs, stake),
    }


def engine(conn: sqlite3.Connection) -> dict:
    ticks = rows(conn, "SELECT * FROM job_runs WHERE job='tick' ORDER BY id DESC LIMIT 10")
    for t in ticks:
        t["summary"] = json.loads(t["summary"] or "{}")
    leagues = []
    for lg in LEAGUES:
        counts = conn.execute(
            "SELECT SUM(status='finished'), SUM(status='scheduled'), "
            "(SELECT COUNT(DISTINCT p.match_id) FROM player_match_stats p JOIN matches x "
            "ON x.id=p.match_id WHERE x.league=?) FROM matches WHERE league=?",
            (lg.code, lg.code),
        ).fetchone()
        leagues.append(
            {
                "code": lg.code,
                "name": lg.name,
                "results": counts[0] or 0,
                "scheduled": counts[1] or 0,
                "rosters": counts[2] or 0,
                "baseline": latest_model(conn, lg.code, "baseline-v1"),
                "xi": latest_model(conn, lg.code, "xi-v2"),
                "active": get_setting(conn, f"strategy:{lg.code}", {}).get(
                    "active_model", "baseline-v1"
                ),
                "synced": get_setting(conn, f"synced:{lg.code}"),
                "odds": get_setting(conn, f"odds_refreshed:{lg.code}"),
            }
        )
    return {
        "ticks": ticks,
        "leagues": leagues,
        "odds_api": get_setting(conn, "odds_api"),
        "quarantine": rows(conn, "SELECT * FROM quarantine ORDER BY id DESC LIMIT 15"),
        "quarantine_total": conn.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0],
    }
