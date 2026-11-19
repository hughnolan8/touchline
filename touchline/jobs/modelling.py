"""Fit per-league models and store predictions for upcoming fixtures."""

import json
import sqlite3
from datetime import datetime, timedelta

from touchline.db import connect, dump, get_setting, rows
from touchline.model import dixon_coles as dc
from touchline.model.features import FeatureBuilder

MIN_RESULTS = 40
HORIZON_DAYS = 7


def load_results(conn: sqlite3.Connection, league: str, before: str) -> list[dict]:
    return rows(
        conn,
        "SELECT id, home, away, kickoff, hg, ag FROM matches WHERE league=? AND "
        "status='finished' AND hg IS NOT NULL AND kickoff<? ORDER BY kickoff",
        (league, before),
    )


def load_builder(conn: sqlite3.Connection, league: str, before: str) -> FeatureBuilder:
    stats = rows(
        conn,
        "SELECT p.*, m.kickoff FROM player_match_stats p JOIN matches m "
        "ON m.id=p.match_id WHERE m.league=? AND m.kickoff<?",
        (league, before),
    )
    return FeatureBuilder(load_results(conn, league, before), stats)


def latest_model(conn: sqlite3.Connection, league: str, version: str) -> dict | None:
    row = conn.execute(
        "SELECT id, created_at, payload FROM models WHERE league=? AND version=? "
        "ORDER BY id DESC LIMIT 1",
        (league, version),
    ).fetchone()
    return (
        {"id": row["id"], "created_at": row["created_at"], **json.loads(row["payload"])}
        if row
        else None
    )


def fit_league(league: str, at: str) -> dict:
    """Fit the baseline and (with enough XI coverage) the XI model. Returns sample counts."""
    with connect() as conn:
        results = load_results(conn, league, at)
        builder = load_builder(conn, league, at)
        xi_config = get_setting(conn, f"xi_config:{league}")
    fitted = {}
    if len(results) >= MIN_RESULTS:
        model = dc.fit(results, at)
        if model:
            fitted[dc.BASELINE] = model
        features = {r["id"]: f for r in results if (f := builder.historical(r))}
        covered = [r for r in results if r["id"] in features]
        if len(covered) >= MIN_RESULTS:
            model = dc.fit(covered, at, features, dc.XI, xi_config)
            if model:
                fitted[dc.XI] = model
    with connect() as conn:
        for version, model in fitted.items():
            conn.execute(
                "INSERT INTO models(league, version, created_at, samples, payload) "
                "VALUES(?,?,?,?,?)",
                (league, version, at, model["samples"], dump(model)),
            )
    return {version: model["samples"] for version, model in fitted.items()}


def predict_match(
    conn: sqlite3.Connection, match: dict, at: str, lineup: dict | None = None
) -> dict[str, dict]:
    """Forecast with every available model version and store the predictions.

    Returns {version: {"id": prediction id, "probabilities": {...}}}. The XI model only
    forecasts when a confirmed lineup is supplied.
    """
    out = {}
    for version in (dc.BASELINE, dc.XI):
        model = latest_model(conn, match["league"], version)
        if not model or (version == dc.XI and not lineup):
            continue
        features = None
        if version == dc.XI:
            builder = load_builder(conn, match["league"], match["kickoff"])
            features = builder.for_lineup(match["home"], match["away"], lineup, match["kickoff"])
        p = dc.predict(model, match["home"], match["away"], features)
        if not p:
            continue
        probs = p["probabilities"]
        conn.execute(
            "INSERT OR IGNORE INTO predictions(match_id, model_id, version, created_at, "
            "with_lineup, home, draw, away, home_goals, away_goals) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                match["id"],
                model["id"],
                version,
                at,
                int(bool(lineup)),
                probs["home"],
                probs["draw"],
                probs["away"],
                p["home_goals"],
                p["away_goals"],
            ),
        )
        row = conn.execute(
            "SELECT id FROM predictions WHERE match_id=? AND model_id=? AND with_lineup=?",
            (match["id"], model["id"], int(bool(lineup))),
        ).fetchone()
        out[version] = {"id": row["id"], "probabilities": probs}
    return out


def upcoming(conn: sqlite3.Connection, at: str, league: str | None = None) -> list[dict]:
    end = (datetime.fromisoformat(at) + timedelta(days=HORIZON_DAYS)).isoformat()
    sql = "SELECT * FROM matches WHERE status='scheduled' AND kickoff>? AND kickoff<=?"
    args = [at, end]
    if league:
        sql += " AND league=?"
        args.append(league)
    return rows(conn, sql + " ORDER BY kickoff", args)


def predict_upcoming(at: str) -> int:
    """Baseline forecasts for every fixture in the next seven days (one per model fit)."""
    with connect() as conn:
        return sum(bool(predict_match(conn, m, at)) for m in upcoming(conn, at))
