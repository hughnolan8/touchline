# Data sources

Files: `touchline/sources/*` (`football_data.py` first), `touchline/jobs/ingest.py`, `touchline/jobs/odds.py`,
`touchline/teams.py`

| Source | What | Cost / limits |
|---|---|---|
| football-data.co.uk CSVs | Results (season files) and next week's fixtures (`fixtures.csv`) | Free, no key |
| Understat (`understatapi`) | Per-match player xG/xA for the XI model | Free, unofficial; **down since Nov 2026** |
| The Odds API v4 `/odds` | UK 1X2 prices from 10 whitelisted books | 1 credit per league request |
| FotMob (unofficial JSON) | Confirmed starting XIs | Free, unofficial |

- **Identity.** football-data.co.uk is the master fixture list. A fixture is the same match when
  league, canonical home/away team ids and kick-off (within 48 h) agree; new ones get
  `matches.id = "<league>:<home>-<away>:<date>"`. Odds events and FotMob matches join the same way.
  CSV kick-off times are UK local and stored as UTC. A fixture still unplayed 3 days after
  kick-off becomes `postponed` and any bet on it is voided. Team names map through the curated `ALIASES` table in `teams.py`; nothing is fuzzy-matched.
  Anything unmatched goes to the `quarantine` table, shown on the Engine page.
- **Fixture fallback.** If a league has no scheduled fixtures in the next 7 days (e.g. the weekly
  `fixtures.csv` is late), Odds API events become scheduled fixtures so forecasts and bets
  continue; the football-data result later adopts them. Otherwise an unmatched odds event is a
  team-alias gap and goes to quarantine instead of creating a duplicate.
- **Rosters.** Player stats are only needed by the XI model and come from Understat by
  `matches.understat_id`, which nothing currently sets. Until a working roster source is added
  (see the `add-data-source` skill), `xi-v2` cannot be fitted and the baseline bets alone.
- **Odds budget.** A background refresh of all five leagues runs every `ODDS_REFRESH_HOURS`
  (default 24, so 5 credits a day). On top of that, each league is refreshed once when a fixture
  enters its entry window and, unless `ODDS_CLOSING_REFRESH=0`, once in its closing window.
  `ODDS_MAX_REQUESTS_PER_DAY` is a hard cap. Production (`fly.toml`) is tuned for the free
  500-credit plan: cap 16/day, `ODDS_REFRESH_HOURS=8760` (background refresh off) and
  `ODDS_CLOSING_REFRESH=0`, so credits go only to entry prices and bets get no closing line or CLV.
  Predictions then show prices only from about an hour before kick-off, and the fixture
  fallback above is effectively off (it rides on the background refresh).
- **Players across sources.** FotMob names are matched to Understat players by exact normalised
  name within the team. Unmatched players count at the league baseline rate.
