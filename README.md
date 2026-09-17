# Touchline

Touchline is a Premier League-only paper-betting dashboard. It uses Premier League fixtures and completed scores from Understat to fit a time-decayed Dixon–Coles model and compares its 1X2 probabilities with de-vigged UK odds from The Odds API.

The virtual bankroll starts at £1,000. Predictions remain available for all future fixtures, but a paper bet is created only before kick-off on the fixture's UK calendar day, with a complete verified 1X2 market: fractional Kelly for positive value, or a £1 fallback on the least-negative outcome. No real-money bets are placed.

Railway runs an API service and one five-minute engine worker. The worker refreshes a fixture exactly once in its 55–60 minute pre-kickoff window and keeps polling overdue open bets for final scores. The authenticated dashboard includes a full Premier League refresh control for testing.

```sh
.pythonenv/bin/python -m pytest -q
```

## Historical model backtest

Evaluate forecasts against final scores only (no odds or staking) with a
strict walk-forward fit before each fixture. The command imports completed EPL
results from Understat through `understatapi` before evaluating them:

```sh
.pythonenv/bin/python scripts/backtest.py
```

The JSON report includes fixture count, pick accuracy, multiclass log loss,
Brier score, outcome totals, and confidence calibration. Populate the database
with completed seasons first. By default it imports seasons starting in 2021;
use `--start-season 2018 --end-season 2025` for a wider history, or
`--skip-import` to evaluate results already present in the configured database.
For long histories, `--retrain-days 28` reuses a fit for up to 28 calendar days
while retaining a strictly historical training cutoff.

## Railway continuous deployment

The repository remote is GitHub. In Railway, open the project and connect each deployable service (`api` and `engine`) to `hughnolan8/touchline`, select the `main` branch, and enable **Deploy on Push**. Subsequent pushes to `main` will then deploy automatically; the local `scripts/deploy-railway.py` script is only needed for manual deployments.

## Understat cutover

The engine bootstraps the active Premier League season and the prior three seasons from Understat. It refreshes the active season on manual refresh and while settling overdue bets; The Odds API remains the only source of 1X2 prices.

## Confirmed-XI shadow model

Set `API_FOOTBALL_KEY` on the engine service to enable confirmed-lineup polling.
Understat supplies completed-match player xG/xA and historical rosters; API-Football
supplies the upcoming confirmed XI. Touchline keeps these player-adjusted forecasts
in shadow mode: they are shown in prediction details but do not affect paper stakes.
The player backtest is reported as `confirmed_xi` alongside the score-only baseline.

For the one-time datasource cutover, first deploy the updated engine so the reset command is present in its image. Then reset the Railway football, model, prediction, and paper-ledger data from inside that engine service:

```sh
railway ssh --service engine -- python scripts/reset-railway-data.py --confirm
```

`railway run` executes locally and cannot resolve Railway's private PostgreSQL hostname. The reset intentionally starts the paper ledger again at £1,000. The next engine run repopulates the four seasons and fits a fresh model.
