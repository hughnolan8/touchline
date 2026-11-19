import httpx
import pytest

from tests.helpers import load
from touchline.sources import fotmob, odds_api, pushover, understat


def test_odds_api_parses_whitelisted_books_and_rejects_bad_events():
    events, rejected = odds_api.parse(load("odds_api.json"), "E0")
    assert len(events) == 1 and len(rejected) == 1
    event = events[0]
    assert event.kickoff == "2026-03-01T15:00:00+00:00"
    assert {q.bookmaker for q in event.quotes} == {"Bet365", "Sky Bet"}
    assert len(event.quotes) == 6


def test_odds_api_fetch_reads_remaining_credits():
    def handler(request):
        assert request.url.path == "/v4/sports/soccer_epl/odds"
        return httpx.Response(
            200, json=load("odds_api.json"), headers={"x-requests-remaining": "42"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    events, _, remaining = odds_api.fetch("E0", "key", client)
    assert len(events) == 1 and remaining == "42"


def test_odds_api_errors_hide_the_key():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(odds_api.OddsApiError) as error:
        odds_api.fetch("E0", "secret-key", client)
    assert "secret-key" not in str(error.value)


def test_understat_match_and_roster_parsing():
    done, upcoming = (understat.parse_match(m, "E0") for m in load("understat_matches.json"))
    assert done.finished and (done.hg, done.ag) == (2, 1)
    assert done.kickoff == "2026-02-01T15:00:00+00:00"
    assert not upcoming.finished and upcoming.hg is None
    roster = understat.parse_roster(load("understat_roster.json"))
    assert [(p.name, p.side, p.starter) for p in roster] == [
        ("Bukayo Saka", "home", True),
        ("Leandro Trossard", "home", False),
        ("Cole Palmer", "away", True),
    ]


def test_understat_season_start():
    assert understat.season_start("2026-08-01T00:00:00+00:00") == 2026
    assert understat.season_start("2026-03-01T00:00:00+00:00") == 2025


def test_fotmob_finds_match_and_confirmed_lineup():
    def handler(request):
        name = "fotmob_day.json" if request.url.path.endswith("/matches") else "fotmob_details.json"
        return httpx.Response(200, json=load(name))

    with fotmob.FotMob(httpx.Client(transport=httpx.MockTransport(handler))) as client:
        matches = client.day("20260301")
        assert matches[0]["home"]["name"] == "Arsenal"
        lineup = client.lineup(matches[0]["id"])
    assert len(lineup.home) == 11 and lineup.away[0] == "Away Player 0"


def test_fotmob_unconfirmed_lineup_is_ignored():
    payload = load("fotmob_details.json")
    payload["content"]["lineup"]["confirmed"] = False
    assert fotmob.parse_lineup(payload) is None


def test_pushover_is_a_no_op_without_credentials():
    assert pushover.send("t", "m") is False
