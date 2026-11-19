from datetime import datetime, timedelta

import pytest

from tests.conftest import make_results
from touchline import scheduler
from touchline.db import connect, rows
from touchline.types import Fixture, Lineup, OddsEvent, Quote

NAMES = {
    "arsenal": "Arsenal",
    "chelsea": "Chelsea",
    "liverpool": "Liverpool",
    "everton": "Everton",
    "spurs": "Tottenham",
    "villa": "Aston Villa",
}
AT = "2026-01-10T14:10:00+00:00"
KICKOFF = "2026-01-10T15:00:00+00:00"


def fixture(result, finished=True):
    return Fixture(
        "",
        "E0",
        NAMES[result["home"]],
        NAMES[result["away"]],
        result["kickoff"],
        finished,
        result["hg"] if finished else None,
        result["ag"] if finished else None,
    )


class Fakes(scheduler.Sources):
    def __init__(self, final_score=None, odds=(4.0, 3.6, 2.0)):
        super().__init__()
        upcoming = {
            "id": "E0:999",
            "home": "arsenal",
            "away": "villa",
            "kickoff": KICKOFF,
            "hg": final_score and final_score[0],
            "ag": final_score and final_score[1],
        }
        season = [fixture(r) for r in make_results(end="2026-01-05T15:00:00+00:00")]
        if final_score:
            season.append(fixture(upcoming))
        week = [] if final_score else [fixture(upcoming, finished=False)]
        self.fetch_results = lambda league, year: (season, []) if league == "E0" else ([], [])
        self.fetch_fixtures = lambda: (week, [])
        self.fetch_roster = lambda match_id: {"h": {}, "a": {}}
        self.odds_calls = []

        def fetch_odds(league, key):
            self.odds_calls.append(league)
            if league != "E0":
                return [], [], "99"
            stamp = self.now
            quotes = [
                Quote("Bet365", s, o, stamp)
                for s, o in zip(("home", "draw", "away"), odds, strict=True)
            ]
            return [OddsEvent("E0", "Arsenal", "Aston Villa", KICKOFF, quotes)], [], "99"

        self.fetch_odds = fetch_odds
        fake = self

        class FotMob:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                pass

            def day(self, date):
                return [{"id": 1, "home": {"name": "Arsenal"}, "away": {"name": "Aston Villa"}}]

            def lineup(self, match_id):
                fake.lineup_calls += 1
                return Lineup([f"H{i}" for i in range(11)], [f"A{i}" for i in range(11)])

        self.fotmob = FotMob
        self.lineup_calls = 0
        self.now = AT


def test_tick_bets_once_at_entry_with_confirmed_xi(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test")
    fakes = Fakes()
    summary = scheduler.tick(AT, fakes)
    assert summary["fitted"] == 1 and summary["entries"] == 1, summary
    assert summary["decisions"] == ["bet: edge above threshold"], summary
    assert scheduler.tick(AT, fakes)["decisions"] == []
    with connect() as conn:
        bets = rows(conn, "SELECT * FROM bets")
    assert len(bets) == 1 and bets[0]["selection"] == "home" and bets[0]["stake"] == 20.0


def test_tick_records_missed_without_odds():
    summary = scheduler.tick(AT, Fakes())  # no ODDS_API_KEY: no entry price
    assert summary["decisions"] == []
    later = (datetime.fromisoformat(AT) + timedelta(minutes=25)).isoformat()
    assert scheduler.tick(later, Fakes())["decisions"] == ["missed: entry odds, confirmed XI"]


def test_closing_line_and_settlement(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test")
    scheduler.tick(AT, Fakes())
    close_at = "2026-01-10T14:57:00+00:00"
    closing = Fakes(odds=(3.5, 3.6, 2.2))
    closing.now = close_at
    assert scheduler.tick(close_at, closing)["closed"] == 1
    after = "2026-01-10T17:30:00+00:00"
    assert scheduler.tick(after, Fakes(final_score=(2, 0)))["settled"] == 1
    with connect() as conn:
        bet = rows(conn, "SELECT * FROM bets")[0]
    assert bet["status"] == "won" and bet["profit"] == 60.0 and bet["clv"] > 0


def test_closing_refresh_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test")
    monkeypatch.setenv("ODDS_CLOSING_REFRESH", "0")
    scheduler.tick(AT, Fakes())
    closing = Fakes(odds=(3.5, 3.6, 2.2))
    closing.now = "2026-01-10T14:57:00+00:00"
    closing.fetch_odds = lambda *a, **k: pytest.fail("closing refresh should be skipped")
    assert scheduler.tick(closing.now, closing)["closed"] == 0
    after = "2026-01-10T17:30:00+00:00"
    assert scheduler.tick(after, Fakes(final_score=(2, 0)))["settled"] == 1
    with connect() as conn:
        bet = rows(conn, "SELECT * FROM bets")[0]
    assert bet["status"] == "won" and bet["clv"] is None


def test_odds_api_supplies_fixtures_when_results_source_has_none(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test")
    down = Fakes()
    down.fetch_fixtures = lambda: ([], [])
    scheduler.tick(AT, down)
    with connect() as conn:
        fixture_rows = rows(conn, "SELECT * FROM matches WHERE status='scheduled'")
    assert len(fixture_rows) == 1
    later = "2026-01-10T17:30:00+00:00"
    scheduler.tick(later, Fakes(final_score=(2, 0)))  # the result adopts the same fixture
    with connect() as conn:
        match = rows(conn, "SELECT * FROM matches WHERE id=?", (fixture_rows[0]["id"],))[0]
        bets = rows(conn, "SELECT status FROM bets")
    assert match["status"] == "finished" and bets == [{"status": "won"}]


def test_unplayed_fixture_is_postponed_and_its_bet_voided(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test")
    scheduler.tick(AT, Fakes())
    days_later = "2026-01-14T12:00:00+00:00"
    assert scheduler.tick(days_later, Fakes())["settled"] == 1
    with connect() as conn:
        bet = rows(conn, "SELECT status, profit FROM bets")[0]
    assert bet == {"status": "void", "profit": 0}
