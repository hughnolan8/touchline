"""Accumulator (parlay) maths: combine single legs into one price. Pure functions only.

Legs are assumed independent, so the combined probability is the product of the legs'
model probabilities. Only one leg per fixture is allowed (same-game legs are correlated).
"""

import math

MAX_LEGS = 12


def combine(legs: list[dict], stake: float) -> dict:
    """Price an accumulator from legs with `match_id`, `probability` and `odds`."""
    if len({leg["match_id"] for leg in legs}) != len(legs):
        raise ValueError("one leg per fixture")
    if not legs:
        empty = ("odds", "probability", "fair_odds", "edge", "kelly", "returns", "expected_profit")
        return {"legs": 0, "stake": stake} | dict.fromkeys(empty)
    odds = math.prod(leg["odds"] for leg in legs)
    probability = math.prod(leg["probability"] for leg in legs)
    edge = probability * odds - 1
    return {
        "legs": len(legs),
        "odds": odds,
        "probability": probability,
        "fair_odds": 1 / probability if probability else None,
        "edge": edge,
        "kelly": max(0.0, edge / (odds - 1)) if odds > 1 else 0.0,
        "stake": stake,
        "returns": round(stake * odds, 2),
        "expected_profit": round(stake * edge, 2),
    }


def candidates(fixture: dict) -> list[dict]:
    """Every priced, forecast outcome of one fixture as a possible leg."""
    probs, prices = fixture.get("probs"), fixture.get("prices") or {}
    if not probs:
        return []
    return [
        {
            "match_id": fixture["id"],
            "selection": sel,
            "probability": probs[sel],
            "odds": prices[sel]["odds"],
            "bookmaker": prices[sel]["bookmaker"],
            "edge": probs[sel] * prices[sel]["odds"] - 1,
        }
        for sel in ("home", "draw", "away")
        if sel in prices
    ]


def pick(fixtures: list[dict], chosen: dict[str, str]) -> list[dict]:
    """Legs for the `{match_id: selection}` choices, skipping anything without a price."""
    legs = []
    for f in fixtures:
        for leg in candidates(f):
            if chosen.get(f["id"]) == leg["selection"]:
                legs.append(leg)
    return legs[:MAX_LEGS]


def suggest(fixtures: list[dict], size: int) -> dict[str, str]:
    """The `size` most likely positive-value legs, at most one per fixture.

    Ranked by model chance first, then edge, so the accumulator is as likely to land as
    possible while every leg still has value.
    """
    rank = lambda leg: (leg["probability"], leg["edge"])  # noqa: E731
    best = []
    for f in fixtures:
        value = [leg for leg in candidates(f) if leg["edge"] > 0]
        if value:
            best.append(max(value, key=rank))
    best.sort(key=rank, reverse=True)
    return {leg["match_id"]: leg["selection"] for leg in best[: min(size, MAX_LEGS)]}
