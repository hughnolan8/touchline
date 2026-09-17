"""Fixture identity and odds normalisation."""
import hashlib
import json
import re
import unicodedata
from .db import COMPETITIONS, dump, now, rows, quarantine

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
