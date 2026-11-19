# Workflow and decision logic

Touchline is a paper-only system. The API serves the dashboard and records
state; the engine performs the scheduled data refresh, forecasting, paper-bet,
and settlement work. A shared portfolio starts at £1,000 across all five
supported leagues.

## System flow

Railway runs the API service and one engine worker. The engine takes a lease
before it runs, so overlapping scheduled or deployment-triggered cycles do not
create duplicate work. Fixture, forecast, quote, decision, bet, and alert
records are persisted in SQLite locally or PostgreSQL on Railway.

```mermaid
flowchart LR
  UI[Dashboard] --> API[FastAPI service]
  API --> DB[(Touchline database)]
  Scheduler[Five-minute engine] --> Lease{Engine lease available?}
  Lease -->|no| Skip[Skip this cycle]
  Lease -->|yes| Bootstrap[Bootstrap / refresh fixtures]
  Bootstrap --> Understat[Understat: results and fixtures]
  Bootstrap --> Train[Train league models]
  Train --> Entry[Pre-kickoff workflow]
  Entry --> Odds[The Odds API: UK 1X2 odds]
  Entry --> Lineups[FotMob: confirmed starting XIs]
  Odds --> DB
  Lineups --> DB
  Entry --> Ledger[Paper ledger and notifications]
  Ledger --> DB
  DB --> API
```

## Engine cycle

The initial bootstrap imports one competition-season batch per cycle until the
current and prior three seasons are present. After bootstrap, a cycle only
refreshes Understat scores when a bet is overdue or in play; roster backfill is
kept as a small separate batch. This bounds startup and keeps the public API
responsive.

For every scheduled fixture in the seven-day horizon, the engine uses these
pre-kickoff windows. Times are minutes before kick-off.

```mermaid
flowchart TD
  Start[Engine cycle] --> Bootstrap{Bootstrap complete?}
  Bootstrap -->|no| Import[Import one league-season batch and train it]
  Bootstrap -->|yes| Prep[Backfill historical rosters; refresh scores if an open bet is overdue]
  Prep --> Window{Fixture timing}
  Window -->|55–60 min| EntryOdds[Fetch verified UK 1X2 odds]
  EntryOdds --> Snapshot[Save one complete initial market snapshot]
  Window -->|30–60 min| XI[Poll FotMob for confirmed XIs]
  XI --> Forecast[Train affected league; save baseline and XI forecasts]
  Forecast --> Decision[Use the league's active model for the paper decision]
  Window -->|under 30 min| Missing[Queue one alert if entry odds or XIs are missing]
  Window -->|0–5 min| Close[Refresh odds and save a closing line for placed bets]
  Decision --> Settle[Settle finished or cancelled bets]
  Missing --> Notify[Retry pending Pushover alerts]
  Close --> Settle
  Settle --> Done[Record engine success and release lease]
  Import --> Done
```

The first complete verified market captured at 55–60 minutes is the entry
market. XI retries do not refresh it, so a later confirmed lineup cannot alter
the recorded paper-bet price. A final market capture near kick-off is stored
only for closing-line-value reporting.

## Forecast and paper-bet decision

Each league has a time-decayed Dixon–Coles model trained from completed
Understat results. The baseline (`baseline-v1`) is the default. A
confirmed-XI model (`xi-v2`) uses the captured XI plus historical player data,
but remains a shadow forecast until an operator promotes it for that league
after its historical and live-observation requirements are met.

```mermaid
flowchart TD
  Fixture[Scheduled fixture] --> Day{UK fixture day and before kick-off?}
  Day -->|no| BlockDay[Record blocked decision]
  Day -->|yes| Entry{Initial complete verified 1X2 snapshot?}
  Entry -->|no| NoMarket[Record no bet]
  Entry -->|yes| XI{Confirmed XI captured?}
  XI -->|no| BlockXI[Wait until cutoff; alert if still missing]
  XI -->|yes| Models[Persist baseline and XI forecasts]
  Models --> Active{Active model available?}
  Active -->|no| BlockModel[Record blocked decision and alert]
  Active -->|yes| Compare[De-vig market; calculate edge for home, draw, away]
  Compare --> Edge{Best edge meets minimum?}
  Edge -->|no| NoEdge[Record no-bet decision]
  Edge -->|yes| Exposure{Portfolio exposure and available bankroll allow it?}
  Exposure -->|no| NoFunds[Record no-bet decision]
  Exposure -->|yes| Stake[Fractional Kelly stake, capped by strategy]
  Stake --> Bet[Create one automatic paper bet and queue notification]
```

The selected outcome is the one with the highest model edge against the
de-vigged market. The engine never submits a bookmaker order. It records the
chosen price, implied market probability, model probability, edge, model
version, and staking inputs in the ledger. The configured strategy controls
minimum edge, maximum exposure, quote freshness, Kelly fraction, maximum bet
fraction, and minimum stake.

## Settlement and dashboard

When Understat confirms a final score, an open bet becomes won, lost, void, or
review (when a score remains incomplete). Settlement is idempotent and uses the
fixed entry snapshot, not the closing line. The dashboard reads the public API
for a shared bankroll/performance summary, selected-league forecasts and bets,
and all-league engine coverage. Its manual refresh endpoints run the same
engine helpers under separate leases; deployment refresh requires its shared
secret header and runs in the background.

## Operational guardrails

- Only the five defined competitions are accepted; unknown leagues return an
  API validation error.
- Provider fixtures are matched using canonical team identities and a bounded
  kickoff window. Ambiguous identities are quarantined rather than guessed.
- A complete market requires all three verified 1X2 outcomes from a bookmaker;
  stale quotes are excluded from decisions.
- Pushover delivery is retry-safe and cannot change whether a paper bet was
  recorded.
- The API health endpoint reports paper mode; engine health becomes unhealthy
  when no successful cycle has been recorded recently.
