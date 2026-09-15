"""Public-file collectors and strict normalisation. No private endpoints or challenge bypasses."""
import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import httpx
from .db import COMPETITIONS, dump, now, rows, quarantine

ZONES={'E0':'Europe/London','SP1':'Europe/Madrid','D1':'Europe/Berlin','I1':'Europe/Rome','F1':'Europe/Paris'}
BOOKS={'B365':'Bet365','BFD':'Betfair Sportsbook','BV':'BetVictor','PP':'Paddy Power','SKB':'Sky Bet'}
# Deliberate aliases only: never fuzzy-join an unfamiliar team onto a priced fixture.
ALIASES={'Manchester United':'Man United','Manchester City':'Man City','Newcastle United':'Newcastle','Nottingham Forest':'Nott\'m Forest','Tottenham Hotspur':'Tottenham','Brighton & Hove Albion':'Brighton','Wolverhampton Wanderers':'Wolves','West Ham United':'West Ham','Leicester City':'Leicester','Leeds United':'Leeds','Ipswich Town':'Ipswich','Coventry City':'Coventry','Hull City':'Hull','Sheffield United':'Sheffield United','West Bromwich Albion':'West Brom','Paris Saint-Germain':'Paris SG','Olympique Lyonnais':'Lyon','Olympique de Marseille':'Marseille','AS Monaco':'Monaco','Stade Rennais':'Rennes','Stade Brestois 29':'Brest','Stade de Reims':'Reims','RC Strasbourg Alsace':'Strasbourg','RC Lens':'Lens','LOSC Lille':'Lille','OGC Nice':'Nice','AJ Auxerre':'Auxerre','Le Havre':'Le Havre','Hellas Verona':'Verona','Internazionale Milano':'Inter','AC Milan':'Milan','AS Roma':'Roma','SSC Napoli':'Napoli','SS Lazio':'Lazio','ACF Fiorentina':'Fiorentina','US Lecce':'Lecce','Atalanta BC':'Atalanta','Parma Calcio 1913':'Parma','Como 1907':'Como','Udinese Calcio':'Udinese','Real Betis Balompié':'Betis','Atlético de Madrid':'Ath Madrid','Atletico Madrid':'Ath Madrid','Athletic Club':'Ath Bilbao','Athletic Club Bilbao':'Ath Bilbao','Deportivo Alavés':'Alaves','RCD Espanyol':'Espanol','RCD Mallorca':'Mallorca','CA Osasuna':'Osasuna','RC Celta de Vigo':'Celta','Celta Vigo':'Celta','Real Sociedad de Fútbol':'Sociedad','Real Sociedad':'Sociedad','Rayo Vallecano de Madrid':'Vallecano','Rayo Vallecano':'Vallecano','Bayern München':'Bayern Munich','Bayern Munich':'Bayern Munich','Borussia Dortmund':'Dortmund','Bayer 04 Leverkusen':'Leverkusen','Bayer Leverkusen':'Leverkusen','Borussia Mönchengladbach':'M\'gladbach','Eintracht Frankfurt':'Ein Frankfurt','VfB Stuttgart':'Stuttgart','VfL Wolfsburg':'Wolfsburg','SC Freiburg':'Freiburg','TSG 1899 Hoffenheim':'Hoffenheim','1899 Hoffenheim':'Hoffenheim','RB Leipzig':'RB Leipzig','1. FSV Mainz 05':'Mainz','FSV Mainz 05':'Mainz','1. FC Union Berlin':'Union Berlin','Union Berlin':'Union Berlin','1. FC Köln':'FC Koln','Hamburger SV':'Hamburg','SV Werder Bremen':'Werder Bremen','Werder Bremen':'Werder Bremen','FC St. Pauli':'St Pauli','FC Augsburg':'Augsburg','1. FC Heidenheim 1846':'Heidenheim'}

ALIASES.update({'AC Monza':'Monza','Angers SCO':'Angers','Bologna FC 1909':'Bologna','Cagliari Calcio':'Cagliari','Club Atlético de Madrid':'Ath Madrid','ES Troyes AC':'Troyes','Frosinone Calcio':'Frosinone','Genoa CFC':'Genoa','Le Havre AC':'Le Havre','Levante UD':'Levante','Lille OSC':'Lille','RC Deportivo La Coruña':'La Coruna','RCD Espanyol de Barcelona':'Espanol','Racing Club de Lens':'Lens','Real Racing Club de Santander':'Santander','SC Paderborn 07':'Paderborn','SV 07 Elversberg':'Elversberg','Stade Rennais FC 1901':'Rennes','US Sassuolo Calcio':'Sassuolo','1. FC Köln':'Koln'})

def norm(name):
    return re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFKD',name).encode('ascii','ignore').decode().lower())

def canonical(c,source,name):
    name=name.strip()
    if not name or len(name)>120:raise ValueError('Invalid team name')
    existing=c.execute('SELECT team_id FROM aliases WHERE source=? AND name=?',(source,name)).fetchone()
    if existing:return existing[0]
    clean=ALIASES.get(name,name)
    if clean==name:
        clean=re.sub(r'^(?:FC |AFC )|(?: FC| AFC| CF)$','',name).strip()
        clean=ALIASES.get(clean,clean)
    ident=norm(clean)
    if not ident:raise ValueError('Invalid team identity')
    c.execute('INSERT OR IGNORE INTO teams VALUES(?,?)',(ident,clean))
    c.execute('INSERT INTO aliases VALUES(?,?,?)',(source,name,ident))
    return ident

def ingest_match(c,source,source_id,competition,home,away,kickoff,confirmed,status,stats,observed=None):
    if competition not in COMPETITIONS:return None
    observed=observed or now();h=canonical(c,source,home);a=canonical(c,source,away)
    if h==a:raise ValueError('Home and away team are identical')
    source_match=c.execute('SELECT m.* FROM matches m JOIN match_aliases a ON a.match_id=m.id WHERE a.source=? AND a.source_id=?',(source,source_id)).fetchone()
    candidates=rows(c,'SELECT * FROM matches WHERE competition=? AND home=? AND away=? AND abs(julianday(kickoff)-julianday(?))<2',(competition,h,a,kickoff))
    if source_match: candidates=[dict(source_match)]
    if len(candidates)>1:
        quarantine(c,source,'Ambiguous fixture identity',dict(home=home,away=away,kickoff=kickoff));return None
    if candidates:
        old=candidates[0];ident=old['id'];oldstats=json.loads(old['stats'])
        if (old['home'],old['away'],old['competition'])!=(h,a,competition):
            quarantine(c,source,'Source identity changed teams or competition',dict(source_id=source_id,home=home,away=away));return None
        c.execute('INSERT OR IGNORE INTO match_aliases VALUES(?,?,?)',(source,source_id,ident))
        if old['source']!=source and old['status']=='finished' and status=='finished' and any(oldstats.get(k)!=stats.get(k) for k in ('hg','ag')):
            quarantine(c,source,'Conflicting full-time result',dict(id=ident,stats=stats));return None
        # A schedule-only provider must not erase results/statistics or verified kickoff times.
        if old['status']=='finished' and status=='scheduled':return ident
        merged={**oldstats,**{k:v for k,v in stats.items() if v is not None}}
        if not confirmed and old['time_confirmed']:kickoff=old['kickoff'];confirmed=True
        if kickoff==old['kickoff'] and int(confirmed)==old['time_confirmed'] and status==old['status'] and merged==oldstats:return ident
        stats=merged
        c.execute('UPDATE matches SET kickoff=?,time_confirmed=?,status=?,stats=?,observed_at=? WHERE id=?',(kickoff,int(confirmed),status,dump(merged),observed,ident))
    else:
        ident=hashlib.sha256(f'{competition}|{h}|{a}|{kickoff[:10]}'.encode()).hexdigest()[:20]
        c.execute('INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?,?)',(ident,competition,h,a,kickoff,int(confirmed),status,dump(stats),source,source_id,observed))
    c.execute('INSERT OR IGNORE INTO match_aliases VALUES(?,?,?)',(source,source_id,ident))
    payload=dict(kickoff=kickoff,status=status,stats=stats,source=source,source_id=source_id)
    c.execute('INSERT OR IGNORE INTO observations(match_id,observed_at,payload) VALUES(?,?,?)',(ident,observed,dump(payload)))
    return ident

def add_quote(c,match_id,market,selection,line,player,bookmaker,odds,quoted_at,collected_at,source,url,verified=False,rules='90min'):
    data=[match_id,market,selection,line,player,rules,bookmaker,odds,quoted_at,source,url,bool(verified)]
    fp=hashlib.sha256(dump(data).encode()).hexdigest()
    c.execute('INSERT OR IGNORE INTO quotes(match_id,market,selection,line,player,rules,bookmaker,odds,quoted_at,collected_at,source,url,verified,fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(match_id,market,selection,line,player,rules,bookmaker,odds,quoted_at,collected_at,source,url,int(verified),fp))

def number(row,key):
    value=row.get(key)
    if value is None or value.strip()=='':return None
    value=float(value)
    if not 0<=value<10000:raise ValueError(f'Invalid {key}')
    return value

def football_csv(c,body,url,observed):
    reader=csv.DictReader(io.StringIO(body.lstrip('\ufeff')))
    if not {'Div','Date','HomeTeam','AwayTeam'}.issubset(reader.fieldnames or []):raise ValueError('CSV schema changed: required fixture headers missing')
    count=0
    for r in reader:
        if r.get('Div') not in ZONES:continue
        try:
            if None in r:raise ValueError('Malformed CSV row: extra columns')
            d=datetime.strptime(r['Date'],'%d/%m/%Y' if len(r['Date'])==10 else '%d/%m/%y')
            confirmed=bool(r.get('Time'));tm=r.get('Time') or '12:00'
            hour,minute=map(int,tm.split(':'));kickoff=d.replace(hour=hour,minute=minute,tzinfo=ZoneInfo('Europe/London')).astimezone(timezone.utc).isoformat()
            stats={k:number(r,v) for k,v in {'hg':'FTHG','ag':'FTAG','hc':'HC','ac':'AC','hy':'HY','ay':'AY','hr':'HR','ar':'AR','hs':'HS','as':'AS','hst':'HST','ast':'AST','hf':'HF','af':'AF'}.items()}
            if any(v is not None and not v.is_integer() for v in stats.values()):raise ValueError('Count statistics must be integers')
            closing=[number(r,'B365C'+s) for s in ('H','D','A')]
            if all(x is not None and x>1 for x in closing):stats['closing_1x2']=closing
            status='finished' if stats['hg'] is not None and stats['ag'] is not None else 'scheduled'
            if status=='finished' and kickoff>observed:raise ValueError('Result appears before kickoff')
            mid=ingest_match(c,'football-data',f"{r['Div']}:{r['Date']}:{r['HomeTeam']}:{r['AwayTeam']}",r['Div'],r['HomeTeam'],r['AwayTeam'],kickoff,confirmed,status,stats,observed)
            if not mid:continue
            count+=1
            # Batch publication has no per-quote timestamp: always indicative, never fresh.
            if status=='scheduled':
                for prefix,book in BOOKS.items():
                    for s,label in [('H','home'),('D','draw'),('A','away')]:
                        price=number(r,prefix+s)
                        if price and price>1:add_quote(c,mid,'1x2',label,None,'',book,price,None,observed,'football-data',url)
                for suffix,label in [('>2.5','over'),('<2.5','under')]:
                    price=number(r,'B365'+suffix)
                    if price and price>1:add_quote(c,mid,'goals',label,2.5,'','Bet365',price,None,observed,'football-data',url)
        except (ValueError,TypeError,KeyError) as e:quarantine(c,'football-data',str(e),r)
    return count



class PublicFiles:
    id='public-files'
    def __init__(self): self.client=httpx.Client(timeout=30,follow_redirects=True,headers={'User-Agent':'TouchlineResearch/1.0 (personal local analysis)'})
    def fetch(self,c,url,source,parser):
        try:
            # PostgreSQL marks the whole transaction failed after a query
            # error.  Isolate each source so one malformed document cannot
            # prevent the remaining sources or the source-health update.
            c.execute('SAVEPOINT source_fetch')
            response=self.client.get(url);response.raise_for_status();body=response.content.decode('utf-8-sig',errors='replace');observed=now()
            if len(body)>8_000_000:raise ValueError('Source document exceeds size limit')
            digest=hashlib.sha256(body.encode()).hexdigest()
            count=parser(c,body,url,observed)
            c.execute('INSERT OR IGNORE INTO snapshots(source,url,observed_at,content_hash,body) VALUES(?,?,?,?,?)',(source,url,observed,digest,body))
            c.execute('INSERT INTO sources VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,records=excluded.records,message=excluded.message',(url,'ok',observed,count,'Public dataset collected; odds timestamps may be unavailable'))
            c.execute('RELEASE SAVEPOINT source_fetch')
            return count
        except Exception as e:
            c.execute('ROLLBACK TO SAVEPOINT source_fetch')
            c.execute('RELEASE SAVEPOINT source_fetch')
            c.execute('INSERT INTO sources VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,message=excluded.message',(url,'error',now(),0,str(e)[:350]))
            return 0
