# App-only release verification — 15 September 2026

## Local checks

- Python: 58 passed; five optional PostgreSQL integration tests skipped because the hosted database is quota-blocked.
- The app API imports successfully without the old website API, worker or CSV upload modules.
- Python regression tests cover ledger concurrency, quote freshness, settlement, quota recovery, prediction reuse/invalidation, overdue detection and database outage recovery.

## Production

- App API: https://api-production-f10dd.up.railway.app
- Railway hosts the API, autonomous engine, trainer and PostgreSQL. No external scheduler is used.
- Successful automatic engine completion and real PostgreSQL integration checks remain blocked by database access. Do not interpret a ready deployment as a healthy engine.

- Swift source syntax check passed.
- iOS simulator tests could not complete: two attempts stalled at Xcode’s SDK stat-cache step. This is not a passing iOS test result.

## Remaining verification

After restoring the database or migrating a verified copy, run `scripts/check-mobile-live.py --require-fresh` twice at least five minutes apart. Confirm the completion timestamp advances without using `--tick`. Then verify a complete forward simulation and settlement with real eligible data.

See [database alternatives and migration sequence](RELIABILITY.md). No replacement database, subscription or migration has been created.
