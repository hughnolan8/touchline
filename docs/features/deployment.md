# Deployment (Fly.io)

Files: `Dockerfile`, `fly.toml`, `.github/workflows/deploy.yml`

There is one machine in `lhr`, running the web UI and scheduler on SQLite, with the
`touchline_data` volume mounted at `/data`. Auto-stop is off so the scheduler keeps running.

The machine is a shared-cpu-1x with 256MB plus 512MB of disk swap. That keeps the monthly bill
(about $3) under Fly's $5 waiver for personal organisations. The app peaks around 150MB including
a full refit; the swap covers a second process such as `touchline backfill` run over SSH. Fly has
no spending cap, so adding machines, memory or a dedicated IPv4 will start to cost money.

## First-time setup (run once by a human)

```bash
fly launch --no-deploy --copy-config          # pick an app name; it is written to fly.toml
fly volumes create touchline_data --region lhr --size 1
fly secrets set ODDS_API_KEY=... TOUCHLINE_ADMIN_TOKEN=...
fly deploy
fly ssh console -C "touchline backfill --seasons 4"
```

Then enable auto-deploys:
1. Create a deploy token with `fly tokens create deploy` and save it as the GitHub secret `FLY_API_TOKEN`.
2. Set the repository variable `FLY_ENABLED=true`.

## Everyday flow
Merging to `main` runs `ci`, then `deploy`: `flyctl deploy --remote-only` followed by a
`/health` check.

## Rollback

```bash
fly releases            # find the last good image
fly deploy --image registry.fly.io/<app>:<tag>
```

## Notes
- Back up the database with `fly ssh sftp get /data/touchline.sqlite3`.
- `touchline reset --confirm` deletes the database. Never run it in production without
  explicit approval.
