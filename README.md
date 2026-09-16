# Touchline web dashboard

Browser dashboard for automatic football predictions and paper simulations. All balances and entries use virtual money.

## Project

- `web/`: responsive dashboard served by the Railway API. The owner token exists only for the current browser session.
- `backend/mobile/`: authenticated API, durable scheduling, provider budget and automatic selections.
- `backend/`: models, source parsing, PostgreSQL adapter and transactional paper ledger.
- `backend/runner.py`: autonomous engine and isolated training supervisors.
- `Dockerfile` and `scripts/`: Railway deployment and verification.

Railway hosts the website, API, engine, trainer and PostgreSQL. The engine works while no browser is open. Sports data comes from The Odds API and Football-Data.

## Install and operate

See [backend operations](docs/MOBILE_BACKEND.md) and [reliability](docs/RELIABILITY.md).


```sh
python3.12 -m venv .pythonenv
.pythonenv/bin/pip install -r requirements.lock.txt
.pythonenv/bin/python -m pytest -q
```

Deploy to Railway, open the API service's public domain, and enter the private owner token when prompted. The token is not included in the website and is forgotten when the tab closes.

## Release

After signing in with the official Railway CLI:

```sh
python3 scripts/deploy-railway.py
.pythonenv/bin/python scripts/check-mobile-live.py --require-fresh
```

Wait for all deployments to succeed before the live check. Observe two autonomous completions at least five minutes apart. A healthy API alone does not prove the engine is working.

## Coverage

Five domestic leagues: Premier League, La Liga, Bundesliga, Serie A and Ligue 1. Automatic entries use match-result and goal-total markets with fresh, verified bookmaker prices and a trained model. Historical prices cannot trigger automatic entries. No eligible price can correctly mean no entries.

The fresh portfolio starts with £1,000 virtual funds, quarter Kelly sizing, a 2% per-entry cap, 10% maximum outstanding exposure and a 15–60 minute pre-kickoff window. Model estimates and paper results do not establish profitability.
