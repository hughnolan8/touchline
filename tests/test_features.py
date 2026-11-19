import pytest

from touchline.model.features import FeatureBuilder

RESULTS = [
    {
        "id": "m1",
        "home": "a",
        "away": "b",
        "kickoff": "2026-01-01T15:00:00+00:00",
        "hg": 2,
        "ag": 0,
    },
    {
        "id": "m2",
        "home": "b",
        "away": "a",
        "kickoff": "2026-01-08T15:00:00+00:00",
        "hg": 1,
        "ag": 1,
    },
]


def stat(match, kickoff, player, team, xg, starter=True):
    return {
        "match_id": match,
        "kickoff": kickoff,
        "player_id": player,
        "name": f"Player {player}",
        "team_id": team,
        "starter": starter,
        "minutes": 90,
        "xg": xg,
        "xa": 0.1,
    }


def test_features_never_use_the_target_match_or_later():
    stats = [
        stat("m1", RESULTS[0]["kickoff"], "p1", "a", 1.0),
        stat("m2", RESULTS[1]["kickoff"], "p1", "a", 5.0),
    ]
    builder = FeatureBuilder(RESULTS, stats)
    base = builder.baseline(RESULTS[1]["kickoff"])
    before = builder.player_rate("p1", RESULTS[1]["kickoff"], base)
    assert before[0] == pytest.approx(1.0)  # m2 (xG 5.0) would raise this if it leaked
    assert builder.team_context("a", RESULTS[0]["kickoff"])["attack_form"] == 0.0


def test_team_context_uses_prior_results():
    builder = FeatureBuilder(RESULTS, [])
    context = builder.team_context("a", "2026-01-10T00:00:00+00:00")
    assert context["attack_form"] == 1.5 and context["defence_form"] == 0.5


def test_resolve_lineup_names_by_normalised_name():
    builder = FeatureBuilder(RESULTS, [stat("m1", RESULTS[0]["kickoff"], "p1", "a", 1.0)])
    assert builder.resolve("a", ["PLAYER P1", "Nobody"]) == ["p1", None]


def test_historical_needs_two_full_xis():
    builder = FeatureBuilder(RESULTS, [stat("m1", RESULTS[0]["kickoff"], "p1", "a", 1.0)])
    assert builder.historical(RESULTS[0]) is None
