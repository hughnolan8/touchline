# Model

Files: `touchline/model/*`, `touchline/jobs/modelling.py`, `touchline/cli.py`

- **`baseline-v1`.** A time-decayed (365-day half-life) Dixon–Coles Poisson model per league,
  with L2-penalised attack and defence, home advantage, and the low-score correction `rho`. It
  needs at least 40 results; predictions need each team to have at least 8 appearances.
- **`xi-v2`.** The baseline plus six standardised covariates per side:
  - XI xG90 and xA90 (180-day decay, shrunk toward the league mean with a 540-minute prior);
  - rest days and congestion;
  - attack and defence form over the last 5 matches.

  It is trained on historical starting XIs and forecasts only when a confirmed XI exists.
  It needs Understat rosters, which are unavailable while Understat is down, so for now only
  the baseline is fitted.
- **Refits.** Each league is refit when its model is more than 12 hours old. The scheduler
  then forecasts every fixture in the next 7 days with the baseline. At decision time it stores
  both versions' forecasts; the league's `active_model` decides which one bets.
- **Backtest.** `touchline backtest --league E0 [--xi] [--retrain-days 7]` gives walk-forward
  log loss, Brier score, accuracy and calibration. `--xi` compares the three pre-registered XI
  configs with the baseline and stores the result plus the chosen config.
- **Promotion.** `touchline promote --league E0 --model xi-v2` requires `historical_ok` from the
  last XI backtest and at least 200 prospective XI predictions (`--force` overrides).
