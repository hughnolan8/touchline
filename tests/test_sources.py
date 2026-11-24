import json

import httpx
import pytest

from tests.helpers import FIXTURES, load
from touchline.sources import betfair, football_data, fotmob, odds_api, understat


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


def test_understat_roster_parsing():
    roster = understat.parse_roster(load("understat_roster.json"))
    assert [(p.name, p.side, p.starter) for p in roster] == [
        ("Bukayo Saka", "home", True),
        ("Leandro Trossard", "home", False),
        ("Cole Palmer", "away", True),
    ]


def test_football_data_results_and_fixtures():
    text = (FIXTURES / "football_data.csv").read_text()
    fixtures, rejected = football_data.parse(text, {"E0"})
    played, upcoming = fixtures
    assert (played.home, played.hg, played.ag, played.finished) == ("Liverpool", 4, 2, True)
    assert played.kickoff == "2025-08-15T19:00:00+00:00"  # 20:00 BST
    assert not upcoming.finished and upcoming.kickoff == "2026-01-10T15:00:00+00:00"  # GMT
    assert len(rejected) == 1  # bad date


def test_football_data_fetch_follows_redirects_and_names_season():
    def handler(request):
        if request.url.host == "www.football-data.co.uk":
            return httpx.Response(
                302, headers={"location": "https://football-data.co.uk" + request.url.path}
            )
        assert request.url.path == "/mmz4281/2526/E0.csv"
        return httpx.Response(200, content=(FIXTURES / "football_data.csv").read_bytes())

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    fixtures, _ = football_data.fetch_results("E0", 2025, client)
    assert len(fixtures) == 2


def test_season_start():
    assert football_data.season_start("2026-08-01T00:00:00+00:00") == 2026
    assert football_data.season_start("2026-03-01T00:00:00+00:00") == 2025


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


AT_BF = "2026-11-28T14:20:00+00:00"


def test_betfair_parses_open_markets_net_of_commission():
    payload = load("betfair.json")
    events, rejected = betfair.parse(payload["catalogue"], payload["books"], "E0", AT_BF)
    assert [m["marketId"] for m in rejected] == ["1.250000003"]
    first, suspended = events
    assert (first.home, first.away, first.kickoff) == (
        "Arsenal",
        "Man Utd",
        "2026-11-28T15:00:00+00:00",
    )
    # Man Utd's 3.9 has too little money behind it; the rest pay 95% of the profit.
    assert {(q.selection, q.odds, q.bookmaker) for q in first.quotes} == {
        ("home", 2.045, "Betfair Exchange"),
        ("draw", 3.47, "Betfair Exchange"),
    }
    assert all(q.quoted_at == AT_BF for q in first.quotes)
    assert suspended.away == "Nottm Forest" and suspended.quotes == []


def test_betfair_fetch_logs_in_then_lists_and_prices_markets():
    payload, paths = load("betfair.json"), []

    def handler(request):
        paths.append(request.url.path)
        assert request.headers["X-Application"] == "app"
        if request.url.host == "identitysso.betfair.com":
            return httpx.Response(200, json={"status": "SUCCESS", "token": "tok"})
        assert request.headers["X-Authentication"] == "tok"
        body = json.loads(request.content)
        if request.url.path.endswith("listMarketCatalogue/"):
            assert body["filter"]["competitionIds"] == ["10932509"]
            return httpx.Response(200, json=payload["catalogue"])
        assert len(body["marketIds"]) == 3
        return httpx.Response(200, json=payload["books"])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    events, rejected = betfair.fetch("E0", "app", "user", "pw", AT_BF, "2026-12-05", client)
    assert len(events) == 2 and len(rejected) == 1
    assert paths[0] == "/api/login" and len(paths) == 3


def test_betfair_errors_hide_credentials():
    def handler(request):
        return httpx.Response(200, json={"status": "FAIL", "error": "INVALID_USERNAME_OR_PASSWORD"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(betfair.BetfairError) as error:
        betfair.fetch("E0", "secret-app", "user", "secret-pw", AT_BF, "2026-12-05", client)
    assert "secret" not in str(error.value) and "INVALID_USERNAME" in str(error.value)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(betfair.BetfairError) as error:
        betfair.fetch("E0", "secret-app", "user", "secret-pw", AT_BF, "2026-12-05", client)
    assert "secret" not in str(error.value) and "betfair.com" not in str(error.value)
