---
name: run-app
description: Start the Touchline dashboard locally and open it in the browser preview. Use when asked to run, start, preview or screenshot the app, or to check a UI change.
---

1. If `data/demo.sqlite3` is missing, create it with
   `TOUCHLINE_DB=data/demo.sqlite3 uv run python scripts/demo_data.py`. It needs no network.
   For real data, use `uv run touchline backfill --league E0 --seasons 2` against the default DB.
2. Start the server with the `touchline` config in `.claude/launch.json` (the scheduler is off and
   it uses the demo DB). Without the preview tool, run
   `TOUCHLINE_SCHEDULER=0 TOUCHLINE_DB=data/demo.sqlite3 uv run uvicorn touchline.web.app:app --reload`.
3. Check `/`, `/predictions`, `/bets` and `/engine`. Also check them at mobile width (375px):
   there must be no horizontal page scroll.
4. To try admin actions, restart with `TOUCHLINE_ADMIN_TOKEN=dev`; basic-auth password `dev`.
