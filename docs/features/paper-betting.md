# Paper betting engine

Touchline is a paper-betting dashboard for the Premier League, La Liga,
Bundesliga, Serie A, and Ligue 1. It combines each league's Understat results
with a separate time-decayed Dixon–Coles forecast and de-vigged UK 1X2 odds
from The Odds API. It never places real-money bets.

The engine creates a paper bet only on the fixture's UK calendar day before
kick-off, after it has complete verified 1X2 odds and a confirmed line-up. It
uses fractional Kelly for positive value and a £1 fallback on the
least-negative outcome. The entry price is fixed when the bet is recorded; a
final market capture supports closing-line-value reporting.

The confirmed-XI model remains a shadow model until it passes historical checks
and has 200 timestamped live XI/market observations. The baseline model is the
safe default until an operator promotes the XI model explicitly for that
league. The dashboard selector filters fixtures, bets, and engine coverage;
bankroll and exposure remain shared. See the root README for per-league
backtesting and promotion commands.

Historical fixtures are committed incrementally before any optional roster
fetch, so a long provider response cannot delay API startup during a deploy.
The deployment refresh endpoint acknowledges a reserved engine cycle promptly;
the cycle then runs in the background and health checks wait for its result.
Initial multi-league history is imported one competition-season result batch per
engine cycle; roster hydration stays out of that bootstrap path and uses the
shared database cursor so startup and health checks remain bounded on Railway
PostgreSQL as well as local SQLite.
