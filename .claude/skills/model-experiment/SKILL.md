---
name: model-experiment
description: Try a change to Touchline's forecasting model (Dixon–Coles parameters, new features, XI covariates) and judge it with a leak-free walk-forward backtest. Use before changing touchline/model/.
---

1. **Rules.** Read `touchline/model/AGENTS.md` (leakage rules, versions and promotion).
2. **Baseline numbers.** On a backfilled DB, run
   `uv run touchline backtest --league E0 --retrain-days 7`. Add `--xi` to compare with the
   XI model; that needs rosters, so run `touchline backfill --league E0 --rosters` first.
3. **Change.** For a new feature, add it to `XI_FEATURES` in `dixon_coles.py` and compute it in
   `FeatureBuilder.side`. For a new config, add it to `XI_TUNING` before looking at results.
   A materially different model gets a new version string; don't change `baseline-v1` silently.
4. **Leakage tests.** Extend `tests/test_features.py` or `tests/test_backtest.py` to prove the
   new input uses only pre-cutoff data. Run `uv run pytest tests/test_dixon_coles.py
   tests/test_features.py tests/test_backtest.py`.
5. **Report.** Compare log loss and Brier score before and after: lower is better, and both
   must not get worse. Promote only with `touchline promote`, never by editing settings by hand.
6. **Docs.** Update `docs/features/model.md`.
