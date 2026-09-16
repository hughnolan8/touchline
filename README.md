# Touchline

Touchline is a Premier League-only paper-betting dashboard. It uses completed Premier League scores from Football-Data to fit a time-decayed Dixon–Coles model and compares its 1X2 probabilities with de-vigged UK odds from The Odds API.

The virtual bankroll starts at £1,000. Predictions remain available for all future fixtures, but a paper bet is created only before kick-off on the fixture's UK calendar day, with a complete verified 1X2 market: fractional Kelly for positive value, or a £1 fallback on the least-negative outcome. No real-money bets are placed.

Railway runs an API service and one five-minute engine worker. The worker refreshes a fixture exactly once in its 55–60 minute pre-kickoff window and keeps polling overdue open bets for final scores. The authenticated dashboard includes a full Premier League refresh control for testing.

```sh
.pythonenv/bin/python -m pytest -q
```

## Railway continuous deployment

The repository remote is GitHub. In Railway, open the project and connect each deployable service (`api` and `engine`) to `hughnolan8/touchline`, select the `main` branch, and enable **Deploy on Push**. Subsequent pushes to `main` will then deploy automatically; the local `scripts/deploy-railway.py` script is only needed for manual deployments.
