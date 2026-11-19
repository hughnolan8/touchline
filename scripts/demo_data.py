"""Fill the local database with synthetic Premier League data for UI work (no network).

TOUCHLINE_DB=data/demo.sqlite3 uv run python scripts/demo_data.py
"""

import random
from datetime import UTC, datetime, timedelta

from touchline.db import connect, now
from touchline.jobs import ingest, modelling
from touchline.types import Fixture

TEAMS = [
    "Arsenal",
    "Chelsea",
    "Liverpool",
    "Everton",
    "Tottenham",
    "Aston Villa",
    "Brighton",
    "Newcastle United",
]


def main() -> None:
    rng = random.Random(7)
    at = now()
    start = datetime.now(UTC) - timedelta(days=400)
    with connect() as conn:
        for i in range(260):
            home, away = rng.sample(TEAMS, 2)
            kickoff = (start + timedelta(days=1.5 * i)).isoformat(timespec="seconds")
            hg, ag = rng.choice([0, 1, 1, 2, 2, 3]), rng.choice([0, 0, 1, 1, 2])
            ingest.store_fixture(
                conn, Fixture(f"d{i}", "E0", home, away, kickoff, True, hg, ag), at
            )
        for i in range(6):
            home, away = TEAMS[2 * (i % 4)], TEAMS[2 * (i % 4) + 1]
            kickoff = (datetime.now(UTC) + timedelta(hours=20 + 24 * i)).isoformat(
                timespec="seconds"
            )
            fixture = Fixture(f"u{i}", "E0", home, away, kickoff, False)
            match_id = ingest.store_fixture(conn, fixture, at)
            conn.executemany(
                "INSERT OR IGNORE INTO odds_quotes VALUES(?,?,?,?,?,?)",
                [
                    (match_id, "Bet365", s, round(o + rng.uniform(-0.3, 0.3), 2), at, at)
                    for s, o in (("home", 2.2), ("draw", 3.4), ("away", 3.3))
                ],
            )
        settled = [
            m["id"]
            for m in conn.execute(
                "SELECT id FROM matches WHERE status='finished' ORDER BY kickoff DESC LIMIT 25"
            )
        ]
        for i, match_id in enumerate(settled):
            won = rng.random() < 0.45
            stake, odds = 20.0, round(rng.uniform(1.9, 3.6), 2)
            conn.execute(
                "INSERT OR IGNORE INTO bets(match_id, created_at, selection, odds, bookmaker, "
                "stake, edge, probability, model_version, status, profit, settled_at, "
                "close_odds, clv) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    match_id,
                    at,
                    "home",
                    odds,
                    "Bet365",
                    stake,
                    0.06,
                    0.5,
                    "baseline-v1",
                    "won" if won else "lost",
                    round(stake * (odds - 1), 2) if won else -stake,
                    f"2026-01-{i + 1:02d}T18:00:00+00:00",
                    odds - 0.1,
                    1 / (odds - 0.1) - 1 / odds,
                ),
            )
    print(modelling.fit_league("E0", at))
    print(f"predicted {modelling.predict_upcoming(at)} fixtures")


if __name__ == "__main__":
    main()
