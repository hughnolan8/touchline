---
name: change-strategy
description: Change Touchline's paper-betting rules — edge threshold, Kelly fraction, stake caps, exposure, quote age or the fixture timing windows. Use for any staking or bet-selection change.
---

1. **Defaults and validation** live in `Strategy` (`touchline/strategy.py`). Per-league
   overrides are stored in the `settings` table as `strategy:<league>`; change them with
   `strategy.save(conn, "E0", min_edge=0.04)`.
2. **Decision maths** is in `touchline/betting.py` (`decide`, `market`, `edge`). Window
   handling is in `touchline/scheduler.py` (`run`).
3. **Tests.** Add or adjust a case in `tests/test_betting.py`, then run
   `uv run pytest tests/test_betting.py tests/test_scheduler.py`. The scheduler test asserts a
   £20 stake (the 2% cap), so update it if the caps change.
4. **Docs.** Update `docs/features/betting.md`, which lists the defaults.
