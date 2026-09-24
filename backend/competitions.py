"""The five competitions Touchline supports end to end."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Competition:
    code: str
    name: str
    understat: str
    odds_sport: str


COMPETITIONS = (
    Competition('E0', 'Premier League', 'EPL', 'soccer_epl'),
    Competition('SP1', 'La Liga', 'La_Liga', 'soccer_spain_la_liga'),
    Competition('D1', 'Bundesliga', 'Bundesliga', 'soccer_germany_bundesliga'),
    Competition('I1', 'Serie A', 'Serie_A', 'soccer_italy_serie_a'),
    Competition('F1', 'Ligue 1', 'Ligue_1', 'soccer_france_ligue_one'),
)
BY_CODE = {competition.code: competition for competition in COMPETITIONS}


def competition(code):
    try:
        return BY_CODE[code]
    except KeyError:
        raise ValueError(f'Unsupported league: {code}') from None


def name(code):
    return competition(code).name

