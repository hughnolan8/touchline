# model/ — invariants

- Pure functions only: inputs are lists of dicts (`{id, home, away, kickoff, hg, ag}`), no DB.
- No leakage: `fit` sees only results with `kickoff < cutoff`; `FeatureBuilder` reads player
  stats and results strictly before the cutoff. `tests/test_backtest.py` and
  `tests/test_features.py` guard this — extend them for any new feature.
- Versions: `baseline-v1` (team strengths) and `xi-v2` (+6 confirmed-XI covariates). Fitted
  parameters are stored as JSON in the `models` table by `jobs/modelling.py`.
- Promotion to `xi-v2` needs `touchline backtest --xi` with `historical_ok=True` and ≥200
  prospective XI predictions (`touchline promote`). New tuning configs go in `XI_TUNING` only
  before evaluation, never chosen on in-sample fit.
