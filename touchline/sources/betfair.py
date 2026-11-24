"""Betfair Exchange API: best back prices on each league's MATCH_ODDS markets.

No credits: a (free, delayed) application key plus an account login. Prices are quoted net of
the exchange's commission on winnings so they compare fairly with bookmaker odds.
"""

import math

import httpx

from touchline.db import utc
from touchline.leagues import league
from touchline.types import OddsEvent, Quote

LOGIN_URL = "https://identitysso.betfair.com/api/login"
API_URL = "https://api.betfair.com/exchange/betting/rest/v1.0/"
BOOKMAKER = "Betfair Exchange"
COMMISSION = 0.05
MIN_SIZE = 2.0  # ignore back prices with less money than this available
DRAW = "The Draw"


class BetfairError(Exception):
    pass


def net_odds(price: float) -> float:
    return round(1 + (price - 1) * (1 - COMMISSION), 3)


def parse(
    catalogue: list[dict], books: list[dict], league_code: str, quoted_at: str
) -> tuple[list[OddsEvent], list[dict]]:
    """Join the market catalogue (teams, kick-off) to market books (prices).

    Returns (events, rejected raw markets).
    """
    by_market = {b.get("marketId"): b for b in books}
    events, rejected = [], []
    for market in catalogue:
        try:
            runners = sorted(market["runners"], key=lambda r: r["sortPriority"])
            draw = [r for r in runners if r["runnerName"] == DRAW]
            teams = [r for r in runners if r["runnerName"] != DRAW]
            if len(draw) != 1 or len(teams) != 2:
                raise ValueError("not a 1X2 market")
            sides = {teams[0]["selectionId"]: "home", teams[1]["selectionId"]: "away"}
            sides[draw[0]["selectionId"]] = "draw"
            quotes = []
            book = by_market.get(market["marketId"], {})
            if book.get("status") == "OPEN" and not book.get("inplay"):
                for runner in book.get("runners", []):
                    selection = sides.get(runner.get("selectionId"))
                    best = (runner.get("ex", {}).get("availableToBack") or [{}])[0]
                    price, size = float(best.get("price", 0)), float(best.get("size", 0))
                    ok = runner.get("status") == "ACTIVE" and size >= MIN_SIZE
                    if selection and ok and math.isfinite(price) and 1 < price <= 1000:
                        quotes.append(Quote(BOOKMAKER, selection, net_odds(price), quoted_at))
            kickoff = utc(market["marketStartTime"])
            home, away = teams[0]["runnerName"], teams[1]["runnerName"]
            events.append(OddsEvent(league_code, home, away, kickoff, quotes))
        except (KeyError, TypeError, ValueError, AttributeError):
            rejected.append(market)
    return events, rejected


def _post(client: httpx.Client, url: str, **kwargs):
    try:
        response = client.post(url, **kwargs)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise BetfairError(f"Betfair request failed: {type(error).__name__}") from None


def fetch(
    league_code: str,
    app_key: str,
    username: str,
    password: str,
    at: str,
    horizon: str,
    client: httpx.Client | None = None,
):
    """Log in, list the league's MATCH_ODDS markets kicking off before `horizon`, price them."""
    own = client is None
    client = client or httpx.Client(timeout=25)
    try:
        login = _post(
            client,
            LOGIN_URL,
            data={"username": username, "password": password},
            headers={"X-Application": app_key, "Accept": "application/json"},
        )
        if login.get("status") != "SUCCESS" or not login.get("token"):
            raise BetfairError(f"Betfair login failed: {login.get('error') or 'no token'}")
        headers = {"X-Application": app_key, "X-Authentication": login["token"]}
        market_filter = {
            "eventTypeIds": ["1"],
            "competitionIds": [league(league_code).betfair_competition],
            "marketTypeCodes": ["MATCH_ODDS"],
            "marketStartTime": {"from": at, "to": horizon},
        }
        catalogue = _post(
            client,
            API_URL + "listMarketCatalogue/",
            headers=headers,
            json={
                "filter": market_filter,
                "maxResults": 40,
                "marketProjection": ["RUNNER_DESCRIPTION", "MARKET_START_TIME"],
            },
        )
        ids = [m["marketId"] for m in catalogue if isinstance(m, dict) and "marketId" in m]
        books = (
            _post(
                client,
                API_URL + "listMarketBook/",
                headers=headers,
                json={"marketIds": ids, "priceProjection": {"priceData": ["EX_BEST_OFFERS"]}},
            )
            if ids
            else []
        )
    finally:
        if own:
            client.close()
    return parse(catalogue, books, league_code, at)
