"""The Odds API v4: UK pre-match odds, secret redaction and quota-aware collection."""
import math
from .db import stamp,quarantine
from .providers import ingest_match,add_quote,ALIASES

SPORTS={'E0':'soccer_epl','SP1':'soccer_spain_la_liga','D1':'soccer_germany_bundesliga','I1':'soccer_italy_serie_a','F1':'soccer_france_ligue_one','CL':'soccer_uefa_champs_league','EL':'soccer_uefa_europa_league','ECL':'soccer_uefa_europa_conference_league'}
# Returned UK books only; exchanges are excluded because commission/liquidity is not modelled.
API_BOOKS={'bet365':'Bet365','betfair_sb_uk':'Betfair Sportsbook','betvictor':'BetVictor','paddypower':'Paddy Power','skybet':'Sky Bet','williamhill':'William Hill','ladbrokes_uk':'Ladbrokes','coral':'Coral','unibet_uk':'Unibet','boylesports':'BoyleSports','sport888':'888sport','betway':'Betway','betfred_uk':'Betfred', 'betano_uk':'Betano', 'grosvenor':'Grosvenor','betuk':'BetUK','livescorebet':'LiveScore Bet','virginbet':'Virgin Bet','casumo':'Casumo','leovegas':'LeoVegas','matchbook':None,'betfair_ex_uk':None,'smarkets':None}
ALIASES.update({'Brighton and Hove Albion':'Brighton','Nottingham Forest':'Nott\'m Forest','Wolverhampton Wanderers':'Wolves','Tottenham Hotspur':'Tottenham','Bayern Munich':'Bayern Munich','Borussia Monchengladbach':'M\'gladbach','Bayer Leverkusen':'Leverkusen','FSV Mainz 05':'Mainz','FC Cologne':'Koln','AC Monza':'Monza','Inter Milan':'Inter','AC Milan':'Milan','AS Roma':'Roma','Paris Saint Germain':'Paris SG','Paris Saint-Germain':'Paris SG','Atletico Madrid':'Ath Madrid','Athletic Bilbao':'Ath Bilbao','Celta Vigo':'Celta','Real Betis':'Betis','Espanyol':'Espanol','Deportivo La Coruna':'La Coruna','Racing Santander':'Santander','Stade Rennes':'Rennes','Stade Brestois':'Brest','Stade Reims':'Reims','Saint Etienne':'St Etienne'})

class OddsApiError(Exception):pass

def parse_events(c,events,competition,observed):
    if not isinstance(events,list):raise ValueError('Expected a list of events')
    n=0
    for event in events:
        c.execute('SAVEPOINT odds_event')
        try:
            if event.get('sport_key')!=SPORTS[competition]:raise ValueError('Unexpected competition in API response')
            kickoff=stamp(event['commence_time'])
            if kickoff<=observed:c.execute('RELEASE odds_event');continue
            mid=ingest_match(c,'the-odds-api',str(event['id']),competition,event['home_team'],event['away_team'],kickoff,True,'scheduled',{},observed)
            if not mid:raise ValueError('Unresolved event identity')
            for book in event.get('bookmakers',[]):
                bookmaker=API_BOOKS.get(book['key'])
                if not bookmaker:continue
                for market in book.get('markets',[]):
                    name={'h2h':'1x2','totals':'goals'}.get(market['key'])
                    if not name:continue
                    quoted=market.get('last_update') or book.get('last_update')
                    quoted=stamp(quoted) if quoted else None
                    if quoted and quoted>observed:raise ValueError('API quote timestamp is in the future')
                    for outcome in market.get('outcomes',[]):
                        price=float(outcome['price'])
                        if not math.isfinite(price) or not 1<price<=1001:raise ValueError('Invalid decimal odds')
                        if name=='1x2':
                            selection={event['home_team']:'home',event['away_team']:'away','Draw':'draw'}.get(outcome['name']);line=None
                        else:
                            selection={'Over':'over','Under':'under'}.get(outcome['name']);line=float(outcome['point'])
                            if not math.isfinite(line) or line<0 or line*2!=int(line*2):continue
                        if selection is None:continue
                        link=outcome.get('link') or market.get('link') or book.get('link') or 'https://the-odds-api.com/'
                        if not isinstance(link,str) or not link.startswith('https://'):link='https://the-odds-api.com/'
                        add_quote(c,mid,name,selection,line,'',bookmaker,price,quoted,observed,'the-odds-api',link,bool(quoted))
            n+=1;c.execute('RELEASE odds_event')
        except (ValueError,KeyError,TypeError) as exc:
            c.execute('ROLLBACK TO odds_event');c.execute('RELEASE odds_event');quarantine(c,'the-odds-api',str(exc),event)
    return n

