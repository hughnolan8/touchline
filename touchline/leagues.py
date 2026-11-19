"""The five supported leagues and their provider keys."""

from dataclasses import dataclass


@dataclass(frozen=True)
class League:
    code: str
    name: str
    understat: str
    odds_sport: str


LEAGUES = (
    League("E0", "Premier League", "EPL", "soccer_epl"),
    League("SP1", "La Liga", "La_Liga", "soccer_spain_la_liga"),
    League("D1", "Bundesliga", "Bundesliga", "soccer_germany_bundesliga"),
    League("I1", "Serie A", "Serie_A", "soccer_italy_serie_a"),
    League("F1", "Ligue 1", "Ligue_1", "soccer_france_ligue_one"),
)
BY_CODE = {league.code: league for league in LEAGUES}


def league(code: str) -> League:
    try:
        return BY_CODE[code]
    except KeyError:
        raise ValueError(f"Unsupported league: {code}") from None
