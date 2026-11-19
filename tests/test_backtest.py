from touchline.model import backtest


def test_walk_forward_never_sees_the_scored_result(results, monkeypatch):
    seen = []
    real_fit = backtest.dc.fit

    def spy(records, cutoff, *args, **kwargs):
        seen.append((cutoff, max(r["kickoff"] for r in records)))
        return real_fit(records, cutoff, *args, **kwargs)

    monkeypatch.setattr(backtest.dc, "fit", spy)
    evaluations = backtest.walk_forward(results, minimum_samples=60, retrain_days=30)
    assert evaluations and all(latest < cutoff for cutoff, latest in seen)
    assert all(e["kickoff"] >= cutoff for e in evaluations for cutoff, _ in seen[:1])


def test_summary_metrics(results):
    summary = backtest.summary(backtest.walk_forward(results, 60, 30))
    assert summary["fixtures"] > 0 and 0 < summary["brier"] < 1
    assert sum(summary["outcomes"].values()) == summary["fixtures"]
