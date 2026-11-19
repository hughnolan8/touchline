"""Market consensus, edge, staking, settlement and bankroll maths. Pure functions only."""

import math
import statistics
from datetime import datetime, timedelta

from touchline.strategy import Strategy
from touchline.types import OUTCOMES, Decision, Price, Quote

STARTING_BANKROLL = 1000.0


def devig(prices: dict[str, float]) -> dict[str, float]:
    """Remove the bookmaker margin from one book's complete 1X2 prices."""
    if set(prices) != set(OUTCOMES):
        return {}
    total = sum(1 / odds for odds in prices.values())
    return {sel: 1 / odds / total for sel, odds in prices.items()}


def market(quotes: list[Quote], at: str, max_age_minutes: int) -> dict[str, Price] | None:
    """Median margin-free probability across fresh complete books, plus best price per outcome.

    Only each book's latest quote per selection counts; a book is fresh when all three of
    its quotes are at most `max_age_minutes` old at `at`.
    """
    latest: dict[tuple[str, str], Quote] = {}
    for q in quotes:
        key = (q.bookmaker, q.selection)
        if q.quoted_at <= at and (key not in latest or q.quoted_at > latest[key].quoted_at):
            latest[key] = q
    cutoff = (datetime.fromisoformat(at) - timedelta(minutes=max_age_minutes)).isoformat()
    books: dict[str, dict[str, Quote]] = {}
    for (book, sel), q in latest.items():
        books.setdefault(book, {})[sel] = q
    fresh = {
        b: qs
        for b, qs in books.items()
        if set(qs) == set(OUTCOMES) and min(q.quoted_at for q in qs.values()) >= cutoff
    }
    if not fresh:
        return None
    probs = [devig({s: q.odds for s, q in qs.items()}) for qs in fresh.values()]
    result = {}
    for sel in OUTCOMES:
        best = max((qs[sel] for qs in fresh.values()), key=lambda q: q.odds)
        result[sel] = Price(
            best.odds, best.bookmaker, best.quoted_at, statistics.median(p[sel] for p in probs)
        )
    return result


def edge(probability: float, odds: float) -> float:
    """Expected profit per unit staked."""
    return probability * (odds - 1) - (1 - probability)


def choices(probabilities: dict[str, float], prices: dict[str, Price]) -> list[dict]:
    return [
        {
            "selection": sel,
            "probability": probabilities[sel],
            "odds": p.odds,
            "bookmaker": p.bookmaker,
            "market_probability": p.market_probability,
            "edge": edge(probabilities[sel], p.odds),
        }
        for sel, p in prices.items()
    ]


def _floor(value: float) -> float:
    return math.floor(value * 100) / 100


def decide(
    probabilities: dict[str, float],
    prices: dict[str, Price] | None,
    wallet: dict,
    strategy: Strategy,
) -> Decision:
    """Pick the best-edge outcome and size a fractional-Kelly stake, or explain why not."""
    if not strategy.enabled:
        return Decision("no_bet", "strategy disabled")
    if not prices:
        return Decision("no_bet", "no fresh complete 1X2 market")
    options = choices(probabilities, prices)
    best = max(options, key=lambda c: c["edge"])
    if best["edge"] <= 0 or best["edge"] < strategy.min_edge:
        return Decision("no_bet", "edge below threshold", choices=options)
    balance, reserved = wallet["balance"], wallet["reserved"]
    if reserved / max(balance, 1) >= strategy.max_exposure:
        return Decision("no_bet", "portfolio exposure cap", choices=options)
    odds, p = best["odds"], best["probability"]
    full_kelly = max(0.0, (p * odds - 1) / (odds - 1))
    if strategy.stake_mode == "flat":
        stake = strategy.flat_stake
    else:
        stake = _floor(balance * full_kelly * strategy.kelly_fraction)
    cap = _floor(
        min(
            wallet["available"],
            balance * strategy.max_bet_fraction,
            balance * strategy.max_exposure - reserved,
        )
    )
    stake = min(max(strategy.min_stake, stake), cap)
    if stake < strategy.min_stake:
        return Decision("no_bet", "bankroll unavailable", choices=options)
    return Decision(
        "bet",
        "edge above threshold",
        best["selection"],
        odds,
        best["bookmaker"],
        stake,
        best["edge"],
        p,
        best["market_probability"],
        options,
    )


def settle(selection: str, stake: float, odds: float, hg: int, ag: int) -> tuple[str, float]:
    actual = "home" if hg > ag else "away" if ag > hg else "draw"
    if actual == selection:
        return "won", round(stake * (odds - 1), 2)
    return "lost", -stake


def clv(entry_odds: float, close_odds: float) -> float:
    """Closing-line value as implied-probability gain; positive means we beat the close."""
    return 1 / close_odds - 1 / entry_odds


def account(bets: list[dict], bankroll: float = STARTING_BANKROLL) -> dict:
    """Bankroll, exposure, ROI, drawdown and equity curve from the bets ledger."""
    open_bets = [b for b in bets if b["status"] == "open"]
    settled = sorted(
        (b for b in bets if b["status"] in ("won", "lost", "void")),
        key=lambda b: b["settled_at"] or "",
    )
    risked = [b for b in settled if b["status"] != "void"]
    profit = sum(b["profit"] or 0 for b in settled)
    reserved = sum(b["stake"] for b in open_bets)
    equity = peak = bankroll
    drawdown = 0.0
    curve = [{"at": None, "equity": bankroll}]
    for b in settled:
        equity += b["profit"] or 0
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
        curve.append({"at": b["settled_at"], "equity": round(equity, 2)})
    staked = sum(b["stake"] for b in risked)
    return {
        "balance": round(bankroll + profit, 2),
        "available": round(bankroll + profit - reserved, 2),
        "reserved": round(reserved, 2),
        "profit": round(profit, 2),
        "roi": profit / staked if staked else None,
        "win_rate": sum(b["status"] == "won" for b in risked) / len(risked) if risked else None,
        "settled": len(risked),
        "open": len(open_bets),
        "drawdown": drawdown,
        "curve": curve,
    }
