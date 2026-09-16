# Touchline

Touchline is a Premier League-only paper-betting dashboard. It uses completed Premier League scores from Football-Data to fit a time-decayed Dixon–Coles model and compares its 1X2 probabilities with de-vigged UK odds from The Odds API.

The virtual bankroll starts at £1,000. One bet is created for each fixture with a complete verified 1X2 market: fractional Kelly for positive value, or a £1 fallback on the least-negative outcome. No real-money bets are placed.

Railway runs an API service and one five-minute engine worker. The worker refreshes a fixture exactly once in its 55–60 minute pre-kickoff window and keeps polling overdue open bets for final scores. The authenticated dashboard includes a full Premier League refresh control for testing.

```sh
.pythonenv/bin/python -m pytest -q
```
