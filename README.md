# Touchline

Touchline is a five-league paper-betting dashboard for the Premier League, La Liga, Bundesliga, Serie A, and Ligue 1. It fits one time-decayed Dixon–Coles model per league from Understat fixtures and completed scores, then compares its 1X2 probabilities with de-vigged UK odds from The Odds API.

The virtual bankroll starts at £1,000. Predictions remain available for all future fixtures, but a paper bet is created only before kick-off on the fixture's UK calendar day, with a complete verified 1X2 market: fractional Kelly for positive value, or a £1 fallback on the least-negative outcome. No real-money bets are placed.

Railway runs an API service and one five-minute engine worker. It applies the same odds capture and confirmed-XI flow independently to every supported league. The dashboard's league picker filters fixtures, bets, and coverage; bankroll, exposure, and performance remain one shared £1,000 paper portfolio.

## Pushover bet notifications

Touchline can send an optional phone notification after it records a paper bet. Install Pushover, create a Pushover application, then add these variables to the Railway **engine** service:

```text
PUSHOVER_APP_TOKEN=<application API token>
PUSHOVER_USER_KEY=<your Pushover user key>
```

Optional variables are `PUSHOVER_DEVICE` to target one named device and `PUSHOVER_DASHBOARD_URL` to add an “Open Touchline” link. The API token and user key are secrets: set them only in Railway, never in the repository. Notifications queue with the bet and delivery failures retry on later engine cycles without affecting the paper bet. If the required entry odds, confirmed XIs, or active forecast are unavailable after the 30-minute cutoff, Touchline sends one separate alert naming the missing input.

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

Pass `--league E0`, `SP1`, `D1`, `I1`, or `F1` to backtest one league; without
it the command reports all five. Promote a validated confirmed-XI model only
for its own league, for example:

```sh
.pythonenv/bin/python scripts/promote-model.py --model xi-v2 --league SP1
```

The JSON report includes fixture count, pick accuracy, multiclass log loss,
Brier score, outcome totals, and confidence calibration. Populate the database
with completed seasons first. By default it imports seasons starting in 2021;
use `--start-season 2018 --end-season 2025` for a wider history, or
`--skip-import` to evaluate results already present in the configured database.
For long histories, `--retrain-days 28` reuses a fit for up to 28 calendar days
while retaining a strictly historical training cutoff.

The report also persists a baseline-versus-confirmed-XI candidate evaluation.
The XI model remains a shadow model until it passes its historical checks and
200 timestamped live XI/market observations have accumulated. An operator can
then promote it explicitly (the baseline is the safe default):

```sh
.pythonenv/bin/python scripts/promote-model.py --model xi-v2
```

## Railway continuous deployment

The repository remote is GitHub. Production deploys only from `main`; Railway builds the `api` and `engine` services after each merge. Release branches deploy first to one isolated, shared staging environment, which has its own PostgreSQL database and a five-request daily Odds API limit. See [CI/CD](docs/features/ci-cd.md) for the Railway and GitHub setup, staging-data copy, release gates, and manual rollback procedure.

## Understat cutover

The engine bootstraps the active season and the prior three seasons for every supported league from Understat. It refreshes active seasons on manual refresh and while settling overdue bets; The Odds API remains the only source of 1X2 prices. Its daily request cap is shared across all leagues and should be sized accordingly.

For the one-time datasource cutover, first deploy the updated engine so the reset command is present in its image. Then reset the Railway football, model, prediction, and paper-ledger data from inside that engine service:

```sh
railway ssh --service engine -- python scripts/reset-railway-data.py --confirm
```

`railway run` executes locally and cannot resolve Railway's private PostgreSQL hostname. The reset intentionally starts the paper ledger again at £1,000. The next engine run repopulates the four seasons and fits a fresh model.
