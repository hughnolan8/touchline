# Railway app backend

The Touchline browser dashboard is served from the Railway API service's public domain.

[Railway project](https://railway.com/project/f98e826d-67e5-4458-848a-86c7bb649689)

| Service | Responsibility | Start command |
| --- | --- | --- |
| api | Website, authenticated dashboard API and health endpoints | Dockerfile default: Uvicorn on `$PORT` |
| engine | Five-minute collection, predictions, entries and settlement | `python -m backend.runner --mode engine` |
| trainer | One model-training job per cycle | `python -m backend.runner --mode trainer` |
| Postgres | Durable jobs, models and paper ledger | Railway PostgreSQL template |

All services use the same Railway region and private database network. The three Python services use one replica, sleeping disabled and an `ALWAYS` restart policy. The API deployment check is `/health` with a 120-second startup allowance. Database initialization is serialized across simultaneous deployments.

## Variables and credentials

- All three services: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`.
- API only: `MOBILE_OWNER_TOKEN`.
- Engine only: `MOBILE_ODDS_API_KEY`.
- Trainer: no owner token or provider key.

Private operator configuration is ignored at `data/mobile/railway.json`, with owner-only file permissions. Use the Railway CLI's `variable set KEY --stdin` for secrets. Never put them in Git, command arguments, logs or screenshots. There is no external tick endpoint or scheduler credential.

## Deployment

Install the official Railway CLI, sign in, then run:

```sh
python3 scripts/deploy-railway.py
```

Set `RAILWAY_CLI` to an alternate executable path if needed. The helper explicitly selects the project, production environment and service IDs; it does not reset the database. The Docker build includes only the backend and pinned dependencies. Inspect all service deployments before declaring a release ready.

```sh
railway logs --service engine --lines 50
railway logs --service trainer --lines 50
.pythonenv/bin/python scripts/check-mobile-live.py --require-fresh
```

`/health` checks API/database availability. `/health/engine` returns 503 when no engine cycle has completed in 15 minutes. A recent heartbeat does not imply every provider job succeeded; inspect the authenticated Engine screen for job failures and model readiness. Railway deployment health checks are startup checks, not a continuous external uptime monitor.

## Scheduling and recovery

The engine supervisor starts immediately and runs every five minutes. It kills a stuck child at 240 seconds, before its 280-second lease expires. The trainer has a 900-second timeout and a 960-second lease. Process termination releases local resources; expired database leases recover interrupted work on a later cycle. Jobs retry with bounded backoff, and stale odds/results jobs are superseded instead of consuming credits in a catch-up burst.

Public archives bootstrap four seasons across five leagues. Training waits for archive jobs to finish and runs separately from time-sensitive updates. Entry and settlement writes use database transaction locks and unique ledger constraints. Turning off new entries still allows settlement. The new portfolio starts at £1,000; previous hosted data is not imported.

## Verification and recovery

```sh
.pythonenv/bin/python -m pytest -q
```

PostgreSQL tests require `RUN_MOBILE_POSTGRES_TESTS=1` and `TEST_DATABASE_URL` pointing to a database named `tl_mobile_test_*`. They delete test rows and must never target the live database. Run them from Railway's private network, using a temporary verification deployment when SSH is unavailable.

Keep backups and a continuing Railway plan in place before relying on unattended operation. See [reliability status](RELIABILITY.md) and [verification evidence](MOBILE_VERIFICATION.md). Restore a backup into a separate retained volume, verify ledger and job state, then resume workers. Never reset the live ledger to resolve a deployment failure.
