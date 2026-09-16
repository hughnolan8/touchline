"""The Odds API adapter for Premier League 1X2 prices only."""
import math
from .db import stamp,quarantine
from .providers import ingest_match,add_quote
SPORT='soccer_epl'
BOOKS={'bet365':'Bet365','betfair_sb_uk':'Betfair Sportsbook','betvictor':'BetVictor','paddypower':'Paddy Power','skybet':'Sky Bet','williamhill':'William Hill','ladbrokes_uk':'Ladbrokes','coral':'Coral','unibet_uk':'Unibet','betway':'Betway'}
class OddsApiError(Exception):pass
def parse_events(c,events,observed):
    count=0
    for event in events:
        try:
            if event.get('sport_key')!=SPORT:raise ValueError('Unexpected sport')
            kickoff=stamp(event['commence_time'])
            if kickoff<=observed:continue
            mid=ingest_match(c,'the-odds-api',str(event['id']),'E0',event['home_team'],event['away_team'],kickoff,True,'scheduled',{},observed)
            if not mid:continue
            for book in event.get('bookmakers',[]):
                bookmaker=BOOKS.get(book.get('key'))
                if not bookmaker:continue
                for market in book.get('markets',[]):
                    if market.get('key')!='h2h':continue
                    quoted=stamp(market.get('last_update') or book['last_update'])
                    for item in market.get('outcomes',[]):
                        selection={event['home_team']:'home',event['away_team']:'away','Draw':'draw'}.get(item.get('name'));price=float(item.get('price',0))
                        if selection and math.isfinite(price) and 1<price<=1001:add_quote(c,mid,'1x2',selection,None,'',bookmaker,price,quoted,observed,'the-odds-api','https://the-odds-api.com/',True)
            count+=1
        except (KeyError,TypeError,ValueError) as exc:quarantine(c,'the-odds-api',str(exc),event)
    return count
