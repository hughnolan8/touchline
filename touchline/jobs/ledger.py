"""Paper ledger: market snapshots, bet decisions, closing lines, settlement and alerts."""

import json
import sqlite3
from dataclasses import asdict

from touchline import betting, strategy
from touchline.db import dump, rows
from touchline.jobs.modelling import predict_match
from touchline.sources import pushover
from touchline.types import Price, Quote


def quotes(conn: sqlite3.Connection, match_id: str) -> list[Quote]:
    return [
        Quote(r["bookmaker"], r["selection"], r["odds"], r["quoted_at"])
        for r in rows(conn, "SELECT * FROM odds_quotes WHERE match_id=?", (match_id,))
    ]


def snapshot(
    conn: sqlite3.Connection, match_id: str, kind: str, at: str, max_age: int
) -> dict[str, Price] | None:
    """Store (once) and return the consensus market for `kind` = entry | close."""
    prices = betting.market(quotes(conn, match_id), at, max_age)
    if prices:
        conn.execute(
            "INSERT OR IGNORE INTO market_snapshots VALUES(?,?,?,?)",
            (match_id, kind, at, dump({s: asdict(p) for s, p in prices.items()})),
        )
    return stored_snapshot(conn, match_id, kind)


def stored_snapshot(conn: sqlite3.Connection, match_id: str, kind: str):
    row = conn.execute(
        "SELECT payload FROM market_snapshots WHERE match_id=? AND kind=?", (match_id, kind)
    ).fetchone()
    return {s: Price(**p) for s, p in json.loads(row[0]).items()} if row else None


def wallet(conn: sqlite3.Connection) -> dict:
    return betting.account(rows(conn, "SELECT * FROM bets"))


def record(
    conn: sqlite3.Connection, match_id: str, at: str, action: str, reason: str, payload: dict
) -> str:
    conn.execute(
        "INSERT OR IGNORE INTO decisions(match_id, created_at, action, reason, payload) "
        "VALUES(?,?,?,?,?)",
        (match_id, at, action, reason, dump(payload)),
    )
    return f"{action}: {reason}"


def decide(conn: sqlite3.Connection, match: dict, lineup: dict, at: str) -> str:
    """Forecast with the confirmed XI, then bet at the entry price or record why not."""
    if conn.execute("SELECT 1 FROM decisions WHERE match_id=?", (match["id"],)).fetchone():
        return "already decided"
    rules = strategy.load(conn, match["league"])
    entry = stored_snapshot(conn, match["id"], "entry")
    forecasts = predict_match(conn, match, at, lineup)
    active = forecasts.get(rules.active_model)
    if not active:
        return record(
            conn,
            match["id"],
            at,
            "no_bet",
            f"{rules.active_model} unavailable",
            {"forecasts": forecasts},
        )
    d = betting.decide(active["probabilities"], entry, wallet(conn), rules)
    payload = {"forecasts": forecasts, "choices": d.choices, "model": rules.active_model}
    if d.action == "bet":
        conn.execute(
            "INSERT INTO bets(match_id, prediction_id, created_at, selection, odds, bookmaker, "
            "stake, edge, probability, model_version) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                match["id"],
                active["id"],
                at,
                d.selection,
                d.odds,
                d.bookmaker,
                d.stake,
                d.edge,
                d.probability,
                rules.active_model,
            ),
        )
    return record(conn, match["id"], at, d.action, d.reason, payload)


def missed(conn: sqlite3.Connection, match: dict, at: str) -> str | None:
    """At the decide cutoff, record which required input never arrived."""
    if conn.execute("SELECT 1 FROM decisions WHERE match_id=?", (match["id"],)).fetchone():
        return None
    missing = []
    if not stored_snapshot(conn, match["id"], "entry"):
        missing.append("entry odds")
    if not conn.execute("SELECT 1 FROM lineups WHERE match_id=?", (match["id"],)).fetchone():
        missing.append("confirmed XI")
    return record(
        conn, match["id"], at, "missed", ", ".join(missing) or "not decided", {"missing": missing}
    )


def close(conn: sqlite3.Connection, bet: dict, at: str, max_age: int) -> bool:
    if bet["close_odds"] is not None:
        return False
    prices = snapshot(conn, bet["match_id"], "close", at, max_age)
    if not prices:
        return False
    price = prices[bet["selection"]]
    conn.execute(
        "UPDATE bets SET close_odds=?, close_bookmaker=?, clv=? WHERE id=?",
        (price.odds, price.bookmaker, betting.clv(bet["odds"], price.odds), bet["id"]),
    )
    return True


def settle(conn: sqlite3.Connection, at: str) -> int:
    """Settle open bets whose match has a final score; void postponed ones. Idempotent."""
    voided = conn.execute(
        "UPDATE bets SET status='void', profit=0, settled_at=? WHERE status='open' AND "
        "match_id IN (SELECT id FROM matches WHERE status='postponed')",
        (at,),
    ).rowcount
    due = rows(
        conn,
        "SELECT b.*, m.hg, m.ag FROM bets b JOIN matches m ON m.id=b.match_id "
        "WHERE b.status='open' AND m.status='finished' AND m.hg IS NOT NULL",
    )
    for bet in due:
        status, profit = betting.settle(
            bet["selection"], bet["stake"], bet["odds"], bet["hg"], bet["ag"]
        )
        conn.execute(
            "UPDATE bets SET status=?, profit=?, settled_at=? WHERE id=?",
            (status, profit, at, bet["id"]),
        )
    return len(due) + voided


def notify(conn: sqlite3.Connection) -> int:
    """Send one Pushover alert per bet or missed fixture; unsent ones retry next tick."""
    if not pushover.configured():
        return 0
    pending = rows(
        conn,
        "SELECT d.*, h.name home_name, a.name away_name, b.selection, b.odds, "
        "b.stake, b.edge, b.bookmaker FROM decisions d JOIN matches m ON "
        "m.id=d.match_id JOIN teams h ON h.id=m.home JOIN teams a ON "
        "a.id=m.away LEFT JOIN bets b ON b.match_id=d.match_id WHERE "
        "d.notified=0 AND d.action IN ('bet','missed')",
    )
    sent = 0
    for d in pending:
        fixture = f"{d['home_name']} vs {d['away_name']}"
        if d["action"] == "bet":
            title = "Touchline bet placed"
            body = (
                f"{fixture}\n{d['selection'].title()} @ {d['odds']:.2f} ({d['bookmaker']})\n"
                f"Stake £{d['stake']:.2f} · Edge {d['edge'] * 100:.1f}%"
            )
        else:
            title, body = "Touchline bet not placed", f"{fixture}\nMissing: {d['reason']}"
        if pushover.send(title, body):
            conn.execute("UPDATE decisions SET notified=1 WHERE match_id=?", (d["match_id"],))
            sent += 1
    return sent
