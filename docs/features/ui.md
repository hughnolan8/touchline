# Dashboard

Files: `touchline/web/*`, `touchline/accumulator.py`

| Page | Shows |
|---|---|
| Overview `/` | Balance, profit, ROI, win rate, max drawdown, open exposure, equity curve, recent bets |
| Predictions `/predictions` | Next 7 days: model probabilities, best prices, best-edge outcome, decision |
| Accumulator `/accumulator` | Pick one outcome per upcoming fixture and price the accumulator: combined odds, model chance, fair odds, edge, returns, expected profit, full-Kelly fraction |
| Bets `/bets` | Every paper bet with odds, stake, edge, CLV, status, P&L |
| Engine `/engine` | Per-league data and model freshness, odds credits, last ticks and errors, quarantine, admin actions |

- **League filter.** `?league=E0` filters the pages. The bankroll tiles always cover all
  leagues because the bankroll is shared.
- **Admin actions** (Engine page): run a tick, refresh all odds (5 credits), refit models.
  They need `TOUCHLINE_ADMIN_TOKEN`; the browser asks for basic auth with any username and the
  token as the password.
- **Health.** `/health` returns `{ok, scheduler, last_tick}` and is used by the Fly health check.
- **Accumulator builder.** A calculator, not a bet: nothing is written to the paper ledger.
  Only fixtures with both a forecast and odds are listed, each leg uses the best UK price,
  and the model chance is the product of the legs' probabilities (legs treated as
  independent, one per fixture, at most 12). "Most likely N" fills in the N
  outcomes with the highest model chance, one per fixture, with edge as the tie-break. It
  does not require value: check the Edge tile before trusting the accumulator. The state lives in the query string
  (`?leg.<match_id>=home&stake=10`, or `?auto=3`), so a built accumulator can be shared
  as a link.
