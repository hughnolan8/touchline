# Railway operations

## Production support

Every push to `main` starts the **Production support** GitHub Actions workflow.
It polls the public API for up to ten minutes and writes a pass/fail report to
the job summary. A pass requires `/health`, `/health/engine`, and
`/api/v1/summary` to succeed, with the summary reporting paper mode, a running
engine, and an engine cycle completed after the check started.

The workflow uses no Railway or OpenAI credentials. It validates public
behaviour but cannot identify the exact Railway deployment commit, inspect
service logs, or perform recovery. For diagnosis, ask a Codex agent to inspect
the public endpoints first; it must request approval before making any
production change. Its public API URL is an ordinary workflow environment
value; update it there if the Railway domain changes.

Deploy only `api` and `engine`; remove the former `trainer` service and its variables/jobs. Both services need `DATABASE_URL` and `TOUCHLINE_ODDS_API_KEY`. The dashboard is public and no longer uses an owner token. `MOBILE_ODDS_API_KEY` remains a temporary compatibility fallback while the Railway variable is renamed.

For the Understat cutover, deploy the updated engine first, then run `railway ssh --service engine -- python scripts/reset-railway-data.py --confirm` to reset the existing Railway PostgreSQL football, model, prediction, and paper-ledger data. This runs inside Railway's private network; `railway run` executes locally and cannot reach the private PostgreSQL hostname. The first worker run imports the active Premier League season and the three preceding seasons from Understat, then fits Dixon–Coles. Thereafter it refreshes the active Understat season for settlement and uses The Odds API only for verified 1X2 prices.
