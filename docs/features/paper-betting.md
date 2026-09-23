# Paper betting engine

Touchline is a Premier League-only paper-betting dashboard. It combines
Understat results with a time-decayed Dixon–Coles forecast and de-vigged UK
1X2 odds from The Odds API. It never places real-money bets.

The engine creates a paper bet only on the fixture's UK calendar day before
kick-off, after it has complete verified 1X2 odds and a confirmed line-up. It
uses fractional Kelly for positive value and a £1 fallback on the
least-negative outcome. The entry price is fixed when the bet is recorded; a
final market capture supports closing-line-value reporting.

The confirmed-XI model remains a shadow model until it passes historical checks
and has 200 timestamped live XI/market observations. The baseline model is the
safe default until an operator promotes the XI model explicitly. See the root
README for backtesting and promotion commands.
