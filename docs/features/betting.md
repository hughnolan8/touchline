# Betting (paper only)

Files: `touchline/betting.py`, `touchline/strategy.py`, `touchline/jobs/ledger.py`,
`touchline/scheduler.py`

## Timeline per fixture
Minutes before kick-off, all configurable per league in `Strategy`:

| Window | Action |
|---|---|
| 60 → 30 | Refresh that league's odds once and store the **entry** market. Then poll FotMob each tick; as soon as an XI is confirmed, forecast and decide. |
| ≤ 30 with no decision | Record `missed` with what was absent (entry odds or confirmed XI). |
| ≤ 5 with an open bet | Refresh odds, store the **close** market, compute CLV. Skipped when `ODDS_CLOSING_REFRESH=0` (production), leaving CLV blank. |
| After full time | Settle once football-data.co.uk has the score (idempotent). Void if postponed. |

## Decision rules (`betting.decide`)
- **Market price.**
  - Each book's latest complete 1X2 prices are de-margined.
  - The median across books gives the market probability.
  - The best price per outcome is the price used.
  - Quotes older than `max_quote_age` (15 min) are ignored.
- **Edge.** `p × (odds − 1) − (1 − p)`. The best-edge outcome is bet only if its edge is at
  least `min_edge` (5%).
- **Stake.** Quarter-Kelly (`kelly_fraction`). It is capped at 2% of the bankroll per bet, at
  10% total open exposure, and by available funds, with a £1 minimum. Below the threshold the
  engine records `no_bet`; there is no fallback bet.
- **Ledger.** One decision and at most one bet per fixture. The bankroll starts at £1,000,
  virtual, and is shared by all leagues.
- **Closing-line value.** `1/close − 1/entry`. Positive means the bet beat the closing price.

Change settings in code or with `strategy.save(conn, "E0", min_edge=0.04)`. See the
`change-strategy` skill.
