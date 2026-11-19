import pytest

from touchline import accumulator


def fixture(match_id, probs, odds):
    return {
        "id": match_id,
        "probs": dict(zip(("home", "draw", "away"), probs, strict=True)),
        "prices": {
            s: {"odds": o, "bookmaker": "b"}
            for s, o in zip(("home", "draw", "away"), odds, strict=True)
        },
    }


FIXTURES = [
    fixture("a", (0.5, 0.3, 0.2), (2.2, 3.4, 5.0)),  # home edge +10%
    fixture("b", (0.4, 0.3, 0.3), (2.4, 3.2, 3.0)),  # home edge -4%, draw -4%, away -10%
    fixture("c", (0.25, 0.25, 0.5), (4.0, 4.0, 2.5)),  # away edge +25%
    {"id": "d", "probs": None, "prices": {}},  # no forecast
]


def test_combine_multiplies_odds_and_probabilities():
    legs = [
        {"match_id": "a", "probability": 0.5, "odds": 2.2},
        {"match_id": "c", "probability": 0.5, "odds": 2.5},
    ]
    acca = accumulator.combine(legs, 10)
    assert acca["odds"] == pytest.approx(5.5)
    assert acca["probability"] == pytest.approx(0.25)
    assert acca["fair_odds"] == pytest.approx(4.0)
    assert acca["edge"] == pytest.approx(0.375)
    assert acca["kelly"] == pytest.approx(0.375 / 4.5)
    assert acca["returns"] == 55.0
    assert acca["expected_profit"] == 3.75


def test_combine_handles_empty_and_negative_value():
    assert accumulator.combine([], 10)["odds"] is None
    acca = accumulator.combine([{"match_id": "b", "probability": 0.3, "odds": 3.0}], 10)
    assert acca["edge"] == pytest.approx(-0.1)
    assert acca["kelly"] == 0.0


def test_combine_rejects_two_legs_on_one_fixture():
    leg = {"match_id": "a", "probability": 0.5, "odds": 2.2}
    with pytest.raises(ValueError):
        accumulator.combine([leg, leg], 10)


def test_pick_keeps_only_priced_choices():
    legs = accumulator.pick(FIXTURES, {"a": "home", "c": "away", "d": "home", "x": "draw"})
    assert [(leg["match_id"], leg["selection"]) for leg in legs] == [("a", "home"), ("c", "away")]


def test_suggest_prefers_model_chance_then_edge_among_value_legs():
    # e: favourite 70% at 1.5 (+5%) beats the bigger-edge outsider 20% at 6.0 (+20%).
    e = fixture("e", (0.7, 0.1, 0.2), (1.5, 9.0, 6.0))
    suggested = accumulator.suggest([*FIXTURES, e], 5)
    # 70% first; a and c tie on 50%, so the higher edge (c, +25%) goes first; b has no value.
    assert list(suggested.items()) == [("e", "home"), ("c", "away"), ("a", "home")]
    assert accumulator.suggest([*FIXTURES, e], 1) == {"e": "home"}
