# sources/ — client contract

- Each client fetches and parses one provider and returns `touchline/types.py` dataclasses.
  No DB access, no team resolution (that happens in `jobs/ingest.py` / `jobs/odds.py`).
- Raise the module's own error type with a message that never includes keys or URLs.
- Parsers are pure (`parse_*`) and tested against trimmed payloads in `tests/fixtures/`.
  When recording a new payload, keep only the fields the parser reads.
- The Odds API costs 1 credit per league request (`/odds`, region uk, market h2h). The daily
  cap is enforced in `jobs/odds.py` (`ODDS_MAX_REQUESTS_PER_DAY`).
- FotMob and Understat are unofficial and can change shape; failures are caught per step by
  the scheduler and shown on the Engine page.
