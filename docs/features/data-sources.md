# Data sources

Files: `touchline/sources/*`, `touchline/jobs/ingest.py`, `touchline/jobs/odds.py`,
`touchline/teams.py`

| Source | What | Cost / limits |
|---|---|---|
| Understat (`understatapi`) | Fixtures, results, per-match player xG/xA | Free, unofficial |
| The Odds API v4 `/odds` | UK 1X2 prices from 10 whitelisted books | 1 credit per league request |
| FotMob (unofficial JSON) | Confirmed starting XIs | Free, unofficial |
| Pushover | Alerts | Optional |

- **Identity.** Understat is the master fixture list (`matches.id = "<league>:<understat id>"`).
  Odds events and FotMob matches are joined by canonical team ids (plus kickoff within 48 h for
  odds). Team names map through the curated `ALIASES` table in `teams.py`; nothing is fuzzy-matched.
  Anything unmatched goes to the `quarantine` table, shown on the Engine page.
- **Understat outage fallback.** An Odds API event with no matching fixture in the next 7 days
  becomes a scheduled fixture (`understat_id` NULL), so forecasts and bets continue. When
  Understat recovers it adopts that fixture by teams and kickoff and supplies the result.
  Bets on such fixtures settle only once that happens.
- **Rosters.** Player stats are only needed by the XI model. The tick hydrates 25 matches per
  cycle; `touchline backfill --rosters` fetches them all at once.
- **Odds budget.** A background refresh of all five leagues runs every `ODDS_REFRESH_HOURS`
  (default 24, so 5 credits a day). On top of that, each league is refreshed once when a fixture
  enters its entry window and once in its closing window. `ODDS_MAX_REQUESTS_PER_DAY` is a hard cap.
- **Players across sources.** FotMob names are matched to Understat players by exact normalised
  name within the team. Unmatched players count at the league baseline rate.
