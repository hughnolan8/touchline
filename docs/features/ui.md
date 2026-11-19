# Dashboard

Files: `touchline/web/*`

| Page | Shows |
|---|---|
| Overview `/` | Balance, profit, ROI, win rate, max drawdown, open exposure, equity curve, recent bets |
| Predictions `/predictions` | Next 7 days: model probabilities, best prices, best-edge outcome, decision |
| Bets `/bets` | Every paper bet with odds, stake, edge, CLV, status, P&L |
| Engine `/engine` | Per-league data and model freshness, odds credits, last ticks and errors, quarantine, admin actions |

- **League filter.** `?league=E0` filters the pages. The bankroll tiles always cover all
  leagues because the bankroll is shared.
- **Admin actions** (Engine page): run a tick, refresh all odds (5 credits), refit models.
  They need `TOUCHLINE_ADMIN_TOKEN`; the browser asks for basic auth with any username and the
  token as the password.
- **Health.** `/health` returns `{ok, scheduler, last_tick}` and is used by the Fly health check.
