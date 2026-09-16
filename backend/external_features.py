"""Optional, manually-triggered imports for free xG data sources."""
import json, re
from datetime import datetime, timezone
import httpx
from .db import dump, now, rows, quarantine
from .providers import canonical, ALIASES

UNDERSTAT_LEAGUES = {'E0':'EPL','SP1':'La_liga','D1':'Bundesliga','I1':'Serie_A','F1':'Ligue_1'}

def _date(value):
    if not value:return None
    return str(value)[:10]

def _number(value):
    try:
        value=float(value)
        # Expected goals and ratings are both finite, non-negative source
        # measurements.  Reject malformed or implausibly large values before
        # they can affect an otherwise valid model snapshot.
        return value if value == value and 0 <= value < 10_000 else None
    except (TypeError,ValueError):
        return None

def _understat_rows(payload):
    if isinstance(payload,list):return payload
    if isinstance(payload,dict):
        for key in ('datesData','dates','matches','data'):
            if isinstance(payload.get(key),list):return payload[key]
            if isinstance(payload.get(key),dict) and isinstance(payload[key].get('dates'),list):
                return payload[key]['dates']
    text=payload.decode('utf-8',errors='replace') if isinstance(payload,bytes) else str(payload)
    match=re.search(r"datesData\s*=\s*JSON\.parse\('([^']+)'",text)
    if not match:raise ValueError('Understat payload does not contain datesData')
    return json.loads(bytes(match.group(1),'utf-8').decode('unicode_escape'))

def parse_understat(payload):
    """Normalize Understat league JSON/HTML into dated match xG records."""
    output=[]
    for item in _understat_rows(payload):
        home=item.get('h') or item.get('home')
        away=item.get('a') or item.get('away')
        home=home.get('title') if isinstance(home,dict) else home
        away=away.get('title') if isinstance(away,dict) else away
        xg=item.get('xG')
        # League pages expose xG as {"h": ..., "a": ...}; match-detail
        # exports instead use h_xg/a_xg.  Support both documented shapes.
        hxg=_number(xg.get('h') if isinstance(xg,dict) else item.get('h_xg') or item.get('home_xg'))
        axg=_number(xg.get('a') if isinstance(xg,dict) else item.get('a_xg') or item.get('away_xg'))
        if not home or not away or hxg is None or axg is None:continue
        output.append({'date':_date(item.get('datetime') or item.get('date')),
                       'home':home,'away':away,'hxg':hxg,'axg':axg,
                       'source_id':str(item.get('id',''))})
    return [r for r in output if r['date']]

def _matches(c, competition, date):
    return [m for m in rows(c,'SELECT * FROM matches WHERE competition=?',(competition,))
            if _date(m['kickoff']) == date]

def import_understat(c, competition, payload, observed=None):
    observed=observed or now();count=0
    for item in parse_understat(payload):
        candidates=_matches(c,competition,item['date'])
        home_id=canonical(c,'understat',item['home']);away_id=canonical(c,'understat',item['away'])
        candidates=[m for m in candidates if m['home']==home_id and m['away']==away_id]
        if len(candidates)!=1:
            quarantine(c,'understat','Unmatched or ambiguous fixture',item);continue
        m=candidates[0];stats=json.loads(m['stats'])
        stats.update(hxg=item['hxg'],axg=item['axg'])
        c.execute('UPDATE matches SET stats=?,observed_at=? WHERE id=?',(dump(stats),observed,m['id']))
        c.execute('INSERT OR IGNORE INTO observations(match_id,observed_at,payload) VALUES(?,?,?)',
                  (m['id'],observed,dump({'kickoff':m['kickoff'],'status':m['status'],'stats':stats,
                                          'source':'understat','source_id':item['source_id']})))
        count+=1
    return count

def fetch_understat(competition, season):
    if competition not in UNDERSTAT_LEAGUES:
        raise ValueError('Unsupported Understat competition')
    try:
        season=int(season)
    except (TypeError, ValueError) as error:
        raise ValueError('Invalid Understat season') from error
    if not 2014 <= season <= datetime.now(timezone.utc).year:
        raise ValueError('Invalid Understat season')
    league=UNDERSTAT_LEAGUES[competition]
    # League pages no longer embed match data.  Their client now requests
    # this public JSON endpoint after loading the page.
    url=f'https://understat.com/getLeagueData/{league}/{season}'
    headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
    }
    with httpx.Client(timeout=30,follow_redirects=True,headers=headers) as client:
        response=client.get(url);response.raise_for_status()
        return response.json()

if __name__ == '__main__':
    import argparse
    from .db import init
    parser=argparse.ArgumentParser(description='Import optional Understat features')
    parser.add_argument('--understat', nargs=2, required=True, metavar=('COMPETITION','SEASON'))
    args=parser.parse_args();init()
    with httpx.Client(timeout=30,follow_redirects=True,headers={'User-Agent':'TouchlineResearch/1.0'}) as client:
        competition,season=args.understat
        response=client.get(f'https://understat.com/league/{UNDERSTAT_LEAGUES[competition]}/{season}')
        response.raise_for_status();payload=response.text
        with __import__('backend.db',fromlist=['connect']).connect() as c:
            print(import_understat(c,competition,payload))
