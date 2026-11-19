"""Time-decayed Dixon-Coles goals model with optional confirmed-XI covariates. Pure maths."""

import math
from collections import Counter
from datetime import datetime

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import poisson

BASELINE = "baseline-v1"
XI = "xi-v2"
XI_FEATURES = ("xg90", "xa90", "rest_days", "congestion", "attack_form", "defence_form")
CONFIG = {
    BASELINE: {"half_life_days": 365, "penalty": 3.0, "feature_penalty": 4.0},
    XI: {"half_life_days": 365, "penalty": 4.0, "feature_penalty": 4.0},
}
# Pre-registered grid, only ever compared with walk-forward forecasts.
XI_TUNING = (
    CONFIG[XI],
    {"half_life_days": 240, "penalty": 4.0, "feature_penalty": 5.0},
    {"half_life_days": 365, "penalty": 5.0, "feature_penalty": 6.0},
)
MIN_APPEARANCES = 8
_CLIP = (-3, 2.5)


def score_grid(lam: float, mu: float, rho: float) -> np.ndarray:
    size = max(12, int(max(lam, mu) + 10 * math.sqrt(max(lam, mu))))
    axis = np.arange(size)
    grid = np.outer(poisson.pmf(axis, lam), poisson.pmf(axis, mu))
    grid[0, 0] *= 1 - lam * mu * rho
    grid[0, 1] *= 1 + lam * rho
    grid[1, 0] *= 1 + mu * rho
    grid[1, 1] *= 1 - rho
    grid = np.maximum(grid, 0)
    return grid / max(grid.sum(), 1e-12)


def outcome_probabilities(grid: np.ndarray) -> dict[str, float]:
    return {
        "home": float(np.tril(grid, -1).sum()),
        "draw": float(np.trace(grid)),
        "away": float(np.triu(grid, 1).sum()),
    }


def _standardise(records, features):
    raw = np.array(
        [
            [features[r["id"]][side].get(key, 0.0) for r in records for side in ("home", "away")]
            for key in XI_FEATURES
        ]
    )
    means = raw.mean(axis=1)
    scales = np.maximum(raw.std(axis=1), 0.01)
    home = (raw[:, ::2] - means[:, None]) / scales[:, None]
    away = (raw[:, 1::2] - means[:, None]) / scales[:, None]
    return home, away, means, scales


def fit(
    records: list[dict],
    cutoff: str,
    features: dict | None = None,
    version: str = BASELINE,
    config: dict | None = None,
) -> dict | None:
    """Fit on finished `records` ({id, home, away, kickoff, hg, ag}) before `cutoff`.

    With `features` ({match id: {"home": {...}, "away": {...}}}) covering every record,
    the six XI covariates are added to both goal rates.
    """
    config = config or CONFIG[version]
    teams = sorted({r[k] for r in records for k in ("home", "away")})
    if len(teams) < 2:
        return None
    ids = {team: i for i, team in enumerate(teams)}
    n = len(teams)
    home = np.array([ids[r["home"]] for r in records])
    away = np.array([ids[r["away"]] for r in records])
    hg = np.array([r["hg"] for r in records])
    ag = np.array([r["ag"] for r in records])
    end = datetime.fromisoformat(cutoff)
    ages = np.array(
        [(end - datetime.fromisoformat(r["kickoff"])).total_seconds() / 86400 for r in records]
    )
    weights = np.exp(-math.log(2) * ages / config["half_life_days"])
    use_xi = bool(features) and all(r["id"] in features for r in records)
    if use_xi:
        home_x, away_x, means, scales = _standardise(records, features)
    extra = len(XI_FEATURES) if use_xi else 0
    m00, m01, m10, m11 = (
        (hg == 0) & (ag == 0),
        (hg == 0) & (ag == 1),
        (hg == 1) & (ag == 0),
        (hg == 1) & (ag == 1),
    )

    def loss(p):
        attack = p[:n] - p[:n].mean()
        defence = p[n : 2 * n]
        log_lam = p[-3] + attack[home] + defence[away] + p[-2]
        log_mu = p[-3] + attack[away] + defence[home]
        if use_xi:
            beta = p[2 * n : 2 * n + extra]
            log_lam = log_lam + beta @ home_x
            log_mu = log_mu + beta @ away_x
        lam = np.exp(np.clip(log_lam, *_CLIP))
        mu = np.exp(np.clip(log_mu, *_CLIP))
        rho = p[-1]
        tau = np.ones(len(records))
        tau[m00] = 1 - lam[m00] * mu[m00] * rho
        tau[m01] = 1 + lam[m01] * rho
        tau[m10] = 1 + mu[m10] * rho
        tau[m11] = 1 - rho
        if np.any(tau <= 0):
            return 1e12
        ll = (
            hg * np.log(lam)
            - lam
            - gammaln(hg + 1)
            + ag * np.log(mu)
            - mu
            - gammaln(ag + 1)
            + np.log(tau)
        )
        penalty = config["penalty"] * (np.square(attack).sum() + np.square(defence).sum())
        if use_xi:
            penalty += config["feature_penalty"] * np.square(beta).sum()
        return float(-(weights * ll).sum() + penalty)

    initial = np.zeros(2 * n + extra + 3)
    initial[-3] = math.log(max(float(ag.mean()), 0.3))
    initial[-2] = 0.15
    initial[-1] = -0.03
    bounds = (
        [(-1.5, 1.5)] * (2 * n) + [(-0.6, 0.6)] * extra + [(-1, 1.2), (-0.4, 0.7), (-0.12, 0.08)]
    )
    result = minimize(loss, initial, method="L-BFGS-B", bounds=bounds)
    if not result.success or not math.isfinite(result.fun):
        return None
    p = result.x
    model = {
        "version": version,
        "teams": teams,
        "attack": (p[:n] - p[:n].mean()).tolist(),
        "defence": p[n : 2 * n].tolist(),
        "base": float(p[-3]),
        "home_advantage": float(p[-2]),
        "rho": float(p[-1]),
        "appearances": dict(Counter(r[k] for r in records for k in ("home", "away"))),
        "samples": len(records),
        "config": config,
    }
    if use_xi:
        model["covariates"] = {
            "keys": list(XI_FEATURES),
            "beta": p[2 * n : 2 * n + extra].tolist(),
            "means": means.tolist(),
            "scales": scales.tolist(),
        }
    return model


def predict(model: dict | None, home: str, away: str, features: dict | None = None) -> dict | None:
    """Return {home_goals, away_goals, probabilities} or None if a team is too unfamiliar."""
    if not model or home not in model["teams"] or away not in model["teams"]:
        return None
    seen = model["appearances"]
    if min(seen.get(home, 0), seen.get(away, 0)) < MIN_APPEARANCES:
        return None
    hi, ai = model["teams"].index(home), model["teams"].index(away)
    log_lam = model["base"] + model["attack"][hi] + model["defence"][ai] + model["home_advantage"]
    log_mu = model["base"] + model["attack"][ai] + model["defence"][hi]
    cov = model.get("covariates")
    if cov and features and set(features) == {"home", "away"}:
        means, scales = np.array(cov["means"]), np.array(cov["scales"])
        for side in ("home", "away"):
            values = np.array([features[side].get(key, 0.0) for key in cov["keys"]])
            shift = float(np.dot(cov["beta"], (values - means) / scales))
            if side == "home":
                log_lam += shift
            else:
                log_mu += shift
    lam, mu = math.exp(log_lam), math.exp(log_mu)
    return {
        "home_goals": lam,
        "away_goals": mu,
        "probabilities": outcome_probabilities(score_grid(lam, mu, model["rho"])),
    }
