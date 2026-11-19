# Touchline

Paper-betting automator for the Premier League, La Liga, Bundesliga, Serie A and Ligue 1.
It pulls fixtures and results from football-data.co.uk, UK 1X2 odds from The Odds API and confirmed XIs from
FotMob, forecasts every fixture with a Dixon–Coles model, and places quarter-Kelly **paper**
bets (no real money) shortly before kick-off. A web dashboard shows the bankroll, forecasts,
bets and engine health.

## Quick start

```bash
uv sync                                   # Python 3.12 + deps
uv run touchline backfill --seasons 4     # results for all five leagues, then fit models
uv run uvicorn touchline.web.app:app --reload
```

Open <http://localhost:8000>. The scheduler ticks every 5 minutes inside the web process
(`TOUCHLINE_SCHEDULER=0` disables it). No network? `uv run python scripts/demo_data.py` fills
a database with synthetic data for UI work.

## Configuration (environment)

| Variable | Purpose |
|---|---|
| `ODDS_API_KEY` | The Odds API key (odds are skipped without it) |
| `ODDS_MAX_REQUESTS_PER_DAY` | Optional daily credit cap |
| `ODDS_REFRESH_HOURS` | Background odds refresh interval (default 24) |
| `TOUCHLINE_ADMIN_TOKEN` | Basic-auth password for Engine page actions (disabled if unset) |
| `PUSHOVER_APP_TOKEN`, `PUSHOVER_USER_KEY` | Optional alerts for bets and missed fixtures |
| `TOUCHLINE_DB` | SQLite path (default `data/touchline.sqlite3`) |

## Docs

- Features: [docs/features](docs/features/README.md)
- Development workflow: [docs/engineering-workflow.md](docs/engineering-workflow.md)
- Agents: [AGENTS.md](AGENTS.md)
