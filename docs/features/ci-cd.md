# CI/CD

Touchline promotes a release branch through one shared Railway staging
environment before merging it to production. Release branches are named
`feature/**`, `fix/**`, or `codex/**`; the latest successful branch replaces an
older staging deployment. A staging pass creates a pull request to `main`,
where Codex review and GitHub branch protection control auto-merge.

## One-time Railway setup

Create `staging` as a copy of the production environment, then create a new
PostgreSQL service in staging. Point staging `api` and `engine` at that service
with a Railway `DATABASE_URL` reference and give staging `api` a public domain.
Disable GitHub push deployments for the staging services: GitHub Actions is
their only deployer. Keep production's `api` and `engine` connected to `main`
with Deploy on Push enabled.

Copy the production data once before starting staging. Use two terminals and
Railway database tunnels so neither database needs public networking:

```sh
# Terminal 1: link production Postgres, then leave this tunnel running.
railway link --environment production --service Postgres
railway connect postgres --tunnel-only

# Terminal 2: link staging Postgres, then leave this tunnel running.
railway link --environment staging --service Postgres
railway connect postgres --tunnel-only
```

Use the connection details printed by each tunnel to make a custom-format dump
from production and restore it into staging:

```sh
pg_dump "$PRODUCTION_TUNNEL_URL" --format=custom --no-owner --file=touchline-production.dump
pg_restore --dbname="$STAGING_TUNNEL_URL" --no-owner --exit-on-error touchline-production.dump
```

Compare table counts and spot-check recent rows before enabling staging. Do not
automate this copy or repeat it on each deploy; staging must remain independent
once it is initialized. Enable production daily backups and point-in-time
recovery before allowing automated promotion.

## Staging variables and GitHub environments

In Railway staging, set `TOUCHLINE_ODDS_API_KEY` to the live production Odds
API key and set `TOUCHLINE_ODDS_MAX_REQUESTS_PER_UTC_DAY=5`. Every attempted
Odds API request consumes one reservation before the request is made, including
failed requests and manual refreshes. The sixth request in a UTC day is
rejected. Leave that limit unset in production. Remove every `PUSHOVER_*`
variable from staging.

Create protected GitHub environments named `staging` and `production`. In each
environment, store a Railway project token as `RAILWAY_TOKEN`; tokens must be
scoped to the matching Railway environment. Set repository or environment
variables `RAILWAY_PROJECT_ID` and `STAGING_API_URL` (the latter only needs to
exist for staging). Never commit these tokens or database URLs.

Enable Codex's connected GitHub pull-request review. Protect `main`: require
the GitHub Actions `test` and `validate` job checks, one Codex approval, no
unresolved conversations, and no force pushes. Enable squash auto-merge. Open
one test release PR to verify the exact Codex review identity before making its
approval mandatory.

## Release and rollback

1. A release branch passes Quality, including tests and documentation checks.
2. The staging deploy workflow uploads that exact commit to staging `api` and
   `engine`. Newer release work cancels the older staging run.
3. After both Railway CLI deployments succeed, the staging deploy workflow
   calls staging validation with that commit and branch. It waits for healthy
   public API/engine/summary responses and a fresh engine cycle, then fails on
   structured application failures and traceback signatures in Railway logs.
   Failed diagnostics are retained as a workflow artifact.
4. A passing release creates or updates its PR, requests Codex review, and
   enables GitHub auto-merge. Branch protection prevents merging until the
   required checks and approval pass.
5. Merging to `main` deploys production and runs the production support check.

There is no automatic rollback. To revert application code, run **Roll back
production** from GitHub Actions with the last known-good commit SHA or tag.
The protected `production` environment must approve that dispatch. Investigate
and restore data separately; never roll back a database just because an
application deployment failed.
