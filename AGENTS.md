# Touchline — agent guide

Paper-betting automator: Understat + Odds API + FotMob → Dixon–Coles → paper bets → web UI.
One Python 3.12 process (FastAPI + in-process scheduler) on SQLite, deployed to Fly.io.

## Module map (read only what your change touches)

| File | Purpose |
|---|---|
| `touchline/types.py` | Dataclasses passed between layers — start here |
| `touchline/config.py` | Environment settings, logging |
| `touchline/db.py`, `schema.sql` | Connections, single schema, settings, job runs |
| `touchline/leagues.py`, `teams.py` | League keys; team alias table |
| `touchline/strategy.py` | Betting settings dataclass (per-league overrides) |
| `touchline/betting.py` | Pure maths: devig, consensus, edge, Kelly, settle, account |
| `touchline/model/` | Dixon–Coles fit/predict, XI features, backtest (pure) |
| `touchline/sources/` | Provider clients: return dataclasses, never touch the DB |
| `touchline/jobs/` | `ingest` (Understat/FotMob → DB), `odds`, `modelling` (fit/predict), `ledger` (bets) |
| `touchline/scheduler.py` | The 5-minute tick and its fixture windows |
| `touchline/web/` | Routes, read queries, Jinja templates, CSS |
| `touchline/cli.py` | `touchline backfill/backtest/promote/odds/tick/reset` |

Tests mirror modules (`tests/test_betting.py` ↔ `touchline/betting.py`). Provider payloads
live trimmed in `tests/fixtures/`. Nothing in the suite touches the network.

## Commands

```bash
uv run pytest tests/test_<module>.py      # targeted; full suite runs in ~2 s
uv run ruff check --fix . && uv run ruff format .
uv run touchline --help
```

## Rules

1. Paper only. Never add real-money bet placement.
2. Keep the model leak-free: features and fits use only data before the cutoff/kickoff.
3. Keep layers clean: maths and parsers stay pure; SQL lives in `jobs/` and `web/queries.py`.
4. Keep modules under ~150 lines and one concern each (`scripts/check_size.py` warns at 200).
5. Update the matching `docs/features/` page when behaviour changes (not for refactors).

## Workflow

Branch → PR → `ci` green (lint + tests, < 1 min) → squash-merge → `main` auto-deploys to Fly.
No staging environment. Rollback: `fly releases` then `fly deploy --image <previous image>`.

## Production support

Read-only by default: check `/health` and the Engine page, then `fly status` / `fly logs`.
Never deploy, restart, roll back, change secrets or touch production data without the user's
explicit approval. See the `prod-support` skill.
