from touchline.model import dixon_coles as dc


def test_score_grid_is_a_distribution():
    grid = dc.score_grid(1.5, 1.1, -0.05)
    assert abs(grid.sum() - 1) < 1e-9
    assert abs(sum(dc.outcome_probabilities(grid).values()) - 1) < 1e-9


def test_fit_ranks_stronger_team_higher(results):
    model = dc.fit(results, "2026-01-02T00:00:00+00:00")
    prediction = dc.predict(model, "arsenal", "villa")
    reverse = dc.predict(model, "villa", "arsenal")
    assert prediction["probabilities"]["home"] > reverse["probabilities"]["home"]


def test_predict_refuses_unfamiliar_teams(results):
    model = dc.fit(results[:10], "2026-01-02T00:00:00+00:00")
    assert dc.predict(model, "arsenal", "unknown") is None
    assert dc.predict(model, "arsenal", "villa") is None  # under MIN_APPEARANCES
