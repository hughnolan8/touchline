# Reliability and Railway migration

## Cause and architecture

The former database exceeded its project data-transfer allowance, blocking the API and scheduled engine. The user authorized a fresh paper portfolio rather than waiting to recover the previous ledger.

The app backend now targets Railway PostgreSQL with a persistent API, engine supervisor and separate trainer. The engine runs without the phone, a developer laptop or an external HTTP scheduler. Legacy hosting packages, scheduler code and deployment helpers have been removed. The Odds API and Football-Data remain necessary sports-data sources.

## Implemented safeguards

- PostgreSQL transaction locks and unique constraints prevent duplicate entries and settlements.
- Serialized startup schema initialization handles simultaneous service starts.
- Separate training worker keeps expensive model fits out of the regular engine cycle.
- Hard process deadlines, expiring leases, restart policies and bounded job retries recover interrupted work.
- Private database connections avoid routing database traffic through a public API host.
- No silent SQLite fallback in Railway; missing database configuration fails closed.
- Controlled database-unavailable responses and startup retry.
- API health and separate 15-minute engine-heartbeat health endpoint.
- Avoid repeated prediction generation and model/history downloads when inputs have not changed.
- Latest quote selection in SQL; a newer unverified quote cannot resurrect an old eligible price.
- Scores and imminent fixtures take priority; old provider work is superseded.
- Daily local credit ceiling, provider quota reserve and free quota recheck every six hours.
- Suppressed HTTP client URL logs to keep provider query credentials out of logs.

## Operational limits and next improvements

1. **Continuing Railway allowance:** the account showed a 30-day/$5 trial at provisioning. A continuing plan is needed before that allowance expires. No paid plan has been purchased.
2. **Backups:** the attempt to enable daily volume backups returned Railway `Not Authorized`. Backups are not verified as enabled. Resolve the account/permission restriction in the Railway Postgres Backups panel and test restoration. [Railway backup documentation](https://docs.railway.com/volumes/backups).
3. **Continuous alerting:** `/health/engine` detects stale processing, and the app exposes failed jobs. No out-of-app alert delivery is configured. Railway's deployment health check alone does not continuously monitor the engine. Add an authorized notification destination if alerts are wanted.
4. **Measure capacity:** review real training durations, database growth and Railway usage after bootstrap. The current database volume is 500 MB. Keep capacity headroom; do not delete ledger or quote evidence to save space.
5. **Model readiness:** verify all five leagues train successfully. A heartbeat only confirms a completed cycle; source outages, depleted odds credits and missing eligible prices can still mean no entries.

The system is a paper simulation. Consistent execution and backtested estimates do not demonstrate profitable betting.
