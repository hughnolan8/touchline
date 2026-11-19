"""Walk-forward evaluation: every forecast is fit only on results before its kickoff. Pure."""

import math
from collections import Counter
from datetime import datetime

from touchline.model import dixon_coles as dc
from touchline.model.features import FeatureBuilder
from touchline.types import OUTCOMES


def outcome(hg: int, ag: int) -> str:
    return "home" if hg > ag else "away" if ag > hg else "draw"


def score(probabilities: dict, actual: str) -> dict:
    pick = max(OUTCOMES, key=probabilities.__getitem__)
    return {
        "actual": actual,
        "pick": pick,
        "correct": pick == actual,
        "probabilities": probabilities,
        "log_loss": -math.log(max(probabilities[actual], 1e-15)),
        "brier": sum((probabilities[k] - (k == actual)) ** 2 for k in OUTCOMES) / 3,
    }


def walk_forward(
    results: list[dict],
    minimum_samples: int = 40,
    retrain_days: int = 7,
    builder: FeatureBuilder | None = None,
    config: dict | None = None,
) -> list[dict]:
    """Score each result with a model fit on strictly earlier results.

    One fit is shared by every fixture in the same `retrain_days` interval; its cutoff is
    the first fixture's kickoff in that interval. Pass `builder` to evaluate the XI model.
    """
    if minimum_samples < 1 or retrain_days < 1:
        raise ValueError("minimum_samples and retrain_days must be positive")
    results = sorted(results, key=lambda r: (r["kickoff"], r["id"]))
    version = dc.XI if builder else dc.BASELINE
    features = {}
    if builder:
        features = {r["id"]: f for r in results if (f := builder.historical(r))}
    models: dict[int, dict | None] = {}
    evaluations = []
    for fixture in results:
        if builder and fixture["id"] not in features:
            continue
        interval = datetime.fromisoformat(fixture["kickoff"]).date().toordinal() // retrain_days
        if interval not in models:
            prior = [r for r in results if r["kickoff"] < fixture["kickoff"]]
            if builder:
                prior = [r for r in prior if r["id"] in features]
            models[interval] = (
                dc.fit(prior, fixture["kickoff"], features or None, version, config)
                if len(prior) >= minimum_samples
                else None
            )
        prediction = dc.predict(
            models[interval], fixture["home"], fixture["away"], features.get(fixture["id"])
        )
        if prediction:
            actual = outcome(fixture["hg"], fixture["ag"])
            item = score(prediction["probabilities"], actual)
            evaluations.append({"id": fixture["id"], "kickoff": fixture["kickoff"], **item})
    return evaluations


def summary(evaluations: list[dict], bins: int = 10) -> dict:
    """Accuracy, log loss, Brier score and confidence calibration."""
    total = len(evaluations)
    if not total:
        return {
            "fixtures": 0,
            "accuracy": None,
            "log_loss": None,
            "brier": None,
            "outcomes": {},
            "calibration": [],
        }
    buckets = [[] for _ in range(bins)]
    for item in evaluations:
        confidence = item["probabilities"][item["pick"]]
        buckets[min(int(confidence * bins), bins - 1)].append((confidence, item["correct"]))
    calibration = [
        {
            "range": [i / bins, (i + 1) / bins],
            "fixtures": len(b),
            "mean_confidence": sum(x[0] for x in b) / len(b),
            "observed_accuracy": sum(x[1] for x in b) / len(b),
        }
        for i, b in enumerate(buckets)
        if b
    ]
    return {
        "fixtures": total,
        "accuracy": sum(e["correct"] for e in evaluations) / total,
        "log_loss": sum(e["log_loss"] for e in evaluations) / total,
        "brier": sum(e["brier"] for e in evaluations) / total,
        "outcomes": dict(Counter(e["actual"] for e in evaluations)),
        "calibration": calibration,
    }


def compare(
    results: list[dict], builder: FeatureBuilder, minimum_samples: int = 40, retrain_days: int = 7
) -> dict:
    """Baseline vs the best pre-registered XI config. `historical_ok` is half of promotion."""
    baseline = summary(walk_forward(results, minimum_samples, retrain_days))
    trials = [
        (config, summary(walk_forward(results, minimum_samples, retrain_days, builder, config)))
        for config in dc.XI_TUNING
    ]
    scored = [t for t in trials if t[1]["fixtures"]]
    config, candidate = min(scored, key=lambda t: t[1]["log_loss"]) if scored else trials[0]
    ok = bool(
        candidate["fixtures"] >= minimum_samples
        and baseline["fixtures"] >= minimum_samples
        and candidate["log_loss"] < baseline["log_loss"]
        and candidate["brier"] <= baseline["brier"]
    )
    return {"baseline": baseline, "candidate": candidate, "config": config, "historical_ok": ok}
