"""Dataclasses passed between layers. Read this file to learn every layer's inputs/outputs."""

from dataclasses import dataclass, field

OUTCOMES = ("home", "draw", "away")


@dataclass(frozen=True)
class Fixture:
    """A fixture or result as reported by a source, before team resolution."""

    source_id: str
    league: str
    home: str
    away: str
    kickoff: str  # ISO-8601 UTC
    finished: bool
    hg: int | None = None
    ag: int | None = None


@dataclass(frozen=True)
class PlayerStat:
    """One player's line in a completed match (Understat roster)."""

    player_id: str
    name: str
    side: str  # "home" | "away"
    starter: bool
    minutes: float
    xg: float
    xa: float


@dataclass(frozen=True)
class OddsEvent:
    """One Odds API event with its 1X2 quotes."""

    league: str
    home: str
    away: str
    kickoff: str
    quotes: list["Quote"]


@dataclass(frozen=True)
class Quote:
    bookmaker: str
    selection: str  # "home" | "draw" | "away"
    odds: float
    quoted_at: str


@dataclass(frozen=True)
class Price:
    """Best price and consensus probability for one selection."""

    odds: float
    bookmaker: str
    quoted_at: str
    market_probability: float


@dataclass(frozen=True)
class Lineup:
    """Confirmed starting XIs (player names; ids are provider-specific)."""

    home: list[str]
    away: list[str]


@dataclass(frozen=True)
class Decision:
    """Outcome of the betting rules for one fixture."""

    action: str  # "bet" | "no_bet"
    reason: str
    selection: str | None = None
    odds: float | None = None
    bookmaker: str | None = None
    stake: float = 0.0
    edge: float | None = None
    probability: float | None = None
    market_probability: float | None = None
    choices: list[dict] = field(default_factory=list)
