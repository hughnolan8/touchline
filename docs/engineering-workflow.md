# Engineering workflow

The aim is for every change to cost one short CI run and one automatic deploy.

1. Branch from `main` (`claude/…` or `codex/…`).
2. Make the change and run the targeted test file, then `uv run pytest` (~2 s) and
   `uv run ruff check --fix . && uv run ruff format .`.
3. Update the matching `docs/features/` page when user-visible behaviour changes.
4. Open a PR. The `ci` workflow runs lint, format check, tests and a module-size warning in
   under a minute.
5. Squash-merge (auto-merge is fine). The push to `main` runs `deploy` to Fly.io, which
   checks `/health`.

**Branch protection:** require the `ci` check only. There is no staging environment. Risky
changes can be tried locally against a copy of the production DB
(`fly ssh sftp get /data/touchline.sqlite3`, then `TOUCHLINE_DB=...`).

**Agents:** see [AGENTS.md](../AGENTS.md) and the skills in `.claude/skills/`.
