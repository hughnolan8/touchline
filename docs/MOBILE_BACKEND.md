# Railway operations

Deploy only `api` and `engine`; remove the former `trainer` service and its variables/jobs. Both services need `DATABASE_URL` and `MOBILE_ODDS_API_KEY`. The dashboard is public and no longer uses `MOBILE_OWNER_TOKEN`.

Before deployment, reset the existing Railway PostgreSQL data so the Premier League £1,000 ledger starts cleanly. The first worker run imports four Premier League seasons from Football-Data and fits Dixon–Coles. Thereafter it refreshes complete results only for settlement and uses The Odds API for 1X2 prices.
