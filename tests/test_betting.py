import pytest

from touchline import betting
from touchline.strategy import Strategy
from touchline.types import Price, Quote

AT = "2026-03-01T14:00:00+00:00"
WALLET = {"balance": 1000.0, "available": 1000.0, "reserved": 0.0}


def quotes(book, home, draw, away, at=AT):
    return [
        Quote(book, "home", home, at),
        Quote(book, "draw", draw, at),
        Quote(book, "away", away, at),
    ]


def test_devig_sums_to_one():
    assert sum(betting.devig({"home": 2, "draw": 3, "away": 4}).values()) == pytest.approx(1)
    assert betting.devig({"home": 2, "draw": 3}) == {}


def test_market_uses_median_consensus_and_best_price():
    prices = betting.market(quotes("A", 2.4, 3.4, 3.2) + quotes("B", 2.7, 3.1, 3.0), AT, 15)
    assert prices["home"].odds == 2.7 and prices["home"].bookmaker == "B"
    assert sum(p.market_probability for p in prices.values()) == pytest.approx(1)


def test_market_ignores_stale_and_incomplete_books():
    stale = quotes("A", 2.4, 3.4, 3.2, at="2026-03-01T13:00:00+00:00")
    incomplete = [Quote("B", "home", 2.5, AT)]
    assert betting.market(stale + incomplete, AT, 15) is None


def test_negative_edge_is_no_bet():
    prices = betting.market(quotes("A", 2.4, 3.4, 3.2), AT, 15)
    decision = betting.decide({"home": 0.2, "draw": 0.2, "away": 0.2}, prices, WALLET, Strategy())
    assert decision.action == "no_bet" and decision.reason == "edge below threshold"


def test_positive_edge_stakes_capped_quarter_kelly():
    prices = {
        "home": Price(2.4, "A", AT, 0.4),
        "draw": Price(3.4, "A", AT, 0.3),
        "away": Price(3.2, "A", AT, 0.3),
    }
    decision = betting.decide({"home": 0.6, "draw": 0.2, "away": 0.2}, prices, WALLET, Strategy())
    assert decision.action == "bet" and decision.selection == "home"
    assert decision.stake == 20.0  # quarter-Kelly 107 is capped at 2% of bankroll


def test_exposure_cap_blocks_new_bets():
    prices = {
        "home": Price(2.4, "A", AT, 0.4),
        "draw": Price(3.4, "A", AT, 0.3),
        "away": Price(3.2, "A", AT, 0.3),
    }
    wallet = {"balance": 1000.0, "available": 900.0, "reserved": 100.0}
    decision = betting.decide({"home": 0.6, "draw": 0.2, "away": 0.2}, prices, wallet, Strategy())
    assert decision.reason == "portfolio exposure cap"


def test_settle_and_clv():
    assert betting.settle("home", 10, 2.5, 2, 1) == ("won", 15.0)
    assert betting.settle("draw", 10, 3.0, 2, 1) == ("lost", -10)
    assert betting.clv(2.4, 2.1) > 0


def test_account_tracks_drawdown_and_roi():
    bets = [
        {"status": "won", "stake": 10, "profit": 15, "settled_at": "2026-01-01"},
        {"status": "lost", "stake": 20, "profit": -20, "settled_at": "2026-01-02"},
        {"status": "open", "stake": 5, "profit": None, "settled_at": None},
    ]
    acc = betting.account(bets)
    assert acc["balance"] == 995 and acc["available"] == 990 and acc["open"] == 1
    assert acc["roi"] == pytest.approx(-5 / 30)
    assert acc["drawdown"] == pytest.approx(20 / 1015)


def test_strategy_validates():
    with pytest.raises(ValueError):
        Strategy(min_edge=2)
    with pytest.raises(ValueError):
        Strategy(decide_cutoff=90)
