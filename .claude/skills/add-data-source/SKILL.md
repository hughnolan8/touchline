---
name: add-data-source
description: Add or replace an odds, stats or lineup provider in Touchline. Use when integrating a new API or scraper, or when a provider's payload format changes.
---

1. **Types.** Reuse or extend a dataclass in `touchline/types.py`, such as `Fixture`,
   `OddsEvent`, `Quote` or `Lineup`. Avoid provider-specific shapes beyond `sources/`.
2. **Client.** Create `touchline/sources/<name>.py`. It needs:
   - a pure `parse(...)` returning dataclasses;
   - a thin `fetch(...)` that takes an optional `httpx.Client` so tests can inject a
     `MockTransport`;
   - its own error type, whose messages never include keys or URLs.

   Follow `touchline/sources/AGENTS.md`.
3. **Fixture payload.** Save a trimmed payload to `tests/fixtures/<name>.json`, keeping only
   the fields the parser reads. Add tests to `tests/test_sources.py`.
4. **Wiring.** Store the data in `touchline/jobs/ingest.py` (or a sibling such as `jobs/odds.py`): resolve teams with
   `teams.canonical(conn, "<source>", name)` and quarantine anything unmatched. Add the fetch
   function to `scheduler.Sources` so `tests/test_scheduler.py` can inject a fake.
5. **New team spellings.** Add them to `ALIASES` in `touchline/teams.py`.
6. **Checks.** Run `uv run pytest tests/test_sources.py tests/test_scheduler.py`, then update
   `docs/features/data-sources.md`.
