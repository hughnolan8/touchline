"""The Odds API v4: UK 1X2 prices for a whole league in one request (1 credit per call)."""

import math

import httpx

from touchline.db import utc
from touchline.leagues import league
from touchline.types import OddsEvent, Quote

URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
BOOKS = {
    "bet365": "Bet365",
    "betfair_sb_uk": "Betfair Sportsbook",
    "betvictor": "BetVictor",
    "paddypower": "Paddy Power",
    "skybet": "Sky Bet",
    "williamhill": "William Hill",
    "ladbrokes_uk": "Ladbrokes",
    "coral": "Coral",
    "unibet_uk": "Unibet",
    "betway": "Betway",
}


class OddsApiError(Exception):
    pass


def parse(payload: list[dict], league_code: str) -> tuple[list[OddsEvent], list[dict]]:
    """Return (events, rejected raw events). Only whitelisted UK books and sane prices."""
    events, rejected = [], []
    for raw in payload:
        try:
            home, away = raw["home_team"], raw["away_team"]
            names = {home: "home", away: "away", "Draw": "draw"}
            quotes = []
            for book in raw.get("bookmakers", []):
                name = BOOKS.get(book.get("key"))
                for market in book.get("markets", []) if name else []:
                    if market.get("key") != "h2h":
                        continue
                    quoted_at = utc(market.get("last_update") or book["last_update"])
                    for item in market.get("outcomes", []):
                        selection, price = names.get(item.get("name")), float(item["price"])
                        if selection and math.isfinite(price) and 1 < price <= 1001:
                            quotes.append(Quote(name, selection, price, quoted_at))
            events.append(OddsEvent(league_code, home, away, utc(raw["commence_time"]), quotes))
        except (KeyError, TypeError, ValueError):
            rejected.append(raw)
    return events, rejected


def fetch(league_code: str, api_key: str, client: httpx.Client | None = None):
    """Fetch one league. Returns (events, rejected, credits remaining or None)."""
    params = {
        "apiKey": api_key,
        "regions": "uk",
        "markets": "h2h",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    own = client is None
    client = client or httpx.Client(timeout=25)
    try:
        response = client.get(URL.format(sport=league(league_code).odds_sport), params=params)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise OddsApiError(f"Odds API request failed: {type(error).__name__}") from None
    finally:
        if own:
            client.close()
    events, rejected = parse(payload, league_code)
    return events, rejected, response.headers.get("x-requests-remaining")
