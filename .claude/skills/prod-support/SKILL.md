---
name: prod-support
description: Investigate a Touchline production problem (no bets placed, stale data, errors, site down) read-only and report findings. Use for health checks and incident diagnosis.
---

Read-only by default. Don't deploy, restart, roll back, change secrets, or modify or reset the
database without the user's explicit approval.

1. **Health.** `curl -fsS https://<app>.fly.dev/health` (the app name is in `fly.toml`).
   `last_tick.finished_at` should be under 10 minutes old and `ok` should be 1.
2. **Engine page** (`/engine`). Check:
   - per-league sync, fit and odds times;
   - the last ticks' `errors` (each names the failing step and provider);
   - the quarantine list (unmatched team names mean a missing `ALIASES` entry);
   - the Odds API credits remaining.
3. **Fly.** `fly status`, then `fly logs --no-tail | tail -200`. Tick lines read
   `tick {...}`, and provider failures read `<step> failed: ...`.
4. **Common causes.**
   - Understat or FotMob changed shape (a parser error in `sources/`).
   - Odds credits exhausted or the daily cap hit.
   - A new team spelling.
   - The volume is full (`fly ssh console -C "df -h /data"`).
5. **Report** the evidence, the likely cause and a proposed fix. To reproduce locally, ask
   before downloading the DB (`fly ssh sftp get /data/touchline.sqlite3`), then run with
   `TOUCHLINE_DB=<copy>`.
