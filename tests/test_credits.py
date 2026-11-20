import math

from touchline import credits

W = {"E0": credits.Window(60, 30), "D1": credits.Window(60, 30)}
DAY = "2026-11-21T"


def ko(hhmm):
    return f"{DAY}{hhmm}:00+00:00"


def test_fixtures_close_together_share_one_refresh_timed_for_the_last():
    fixtures = [("E0", ko("15:00")), ("E0", ko("15:15")), ("E0", ko("17:30"))]
    plan = credits.slots(fixtures, W, margin=6)
    assert [(s.kickoffs, s.refresh_at) for s in plan] == [
        ((ko("15:00"), ko("15:15")), ko("14:15")),
        ((ko("17:30"),), ko("16:30")),
    ]


def test_fixtures_too_far_apart_get_separate_refreshes():
    plan = credits.slots([("E0", ko("12:30")), ("E0", ko("13:00"))], W, margin=6)
    assert [s.size for s in plan] == [1, 1]


def test_scarce_credits_go_to_the_biggest_slots_first():
    fixtures = [("E0", ko("12:30"))] + [("D1", ko("14:30"))] * 5 + [("E0", ko("15:00"))] * 3
    plan = credits.slots(fixtures, W, margin=6)
    assert [(s.league, s.size) for s in credits.chosen(plan, 2)] == [("D1", 5), ("E0", 3)]
    assert credits.due(plan, 2, ko("11:45")) == set()  # 12:30 not worth a credit
    assert credits.due(plan, 2, ko("13:30")) == {"D1"}
    assert credits.due(plan, math.inf, ko("11:45")) == {"E0"}


def test_budget_holds_back_credits_for_unpublished_days():
    at, reset = "2026-11-21T00:00:00+00:00", "2026-12-01T00:00:00+00:00"
    assert credits.budget(10, at, "2026-11-28T00:00:00+00:00", reset) == 7
    assert credits.budget(10, at, "2026-12-05T00:00:00+00:00", reset) == 10
    assert credits.budget(None, at, at, reset) == math.inf


def test_next_reset_rolls_over_months_and_clamps_short_months():
    assert credits.next_reset("2026-11-20T21:00:00+00:00", 1) == "2026-12-01T00:00:00+00:00"
    assert credits.next_reset("2026-12-20T21:00:00+00:00", 1) == "2027-01-01T00:00:00+00:00"
    assert credits.next_reset("2027-02-02T00:00:00+00:00", 31) == "2027-02-28T00:00:00+00:00"
    assert credits.next_reset("2026-11-10T00:00:00+00:00", 15) == "2026-11-15T00:00:00+00:00"
