"""Premier League forecasts, discrepancies, and paper ledger."""
import json,math,os,sqlite3
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from .db import connect,rows,now,dump,setting,set_setting
from .models import fit_dixon_coles,predict_1x2
from .playerstats import historical_lineups, lineup_features
LEAGUE='E0';STARTING_BANKROLL=1000.;KELLY_FRACTION=.25;MAX_BET_FRACTION=.02;MIN_FALLBACK_STAKE=1.
def seconds(a,b):return (datetime.fromisoformat(a)-datetime.fromisoformat(b)).total_seconds()
def is_bet_day(kickoff,at):
 """Only wager before kick-off on the fixture's UK calendar day."""
 london=ZoneInfo('Europe/London');kickoff=datetime.fromisoformat(kickoff).astimezone(london);at=datetime.fromisoformat(at).astimezone(london)
 return at.date()==kickoff.date() and at<kickoff
def history(c,cutoff):
 r=[]
 for x in rows(c,"SELECT id,home,away,kickoff,stats FROM matches WHERE competition='E0' AND status='finished' AND kickoff<? ORDER BY kickoff",(cutoff,)):
  s=json.loads(x.pop('stats'))
  if s.get('hg') is not None and s.get('ag') is not None:r.append({**x,'stats':s})
 return r
def train(c,at=None):
 at=at or now();r=history(c,at)
 if len(r)<40:return None
 p=fit_dixon_coles(r,at)
 if not p:return None
 return c.execute('INSERT INTO models(competition,created_at,cutoff,samples,payload,metrics) VALUES(?,?,?,?,?,?)',(LEAGUE,at,at,len(r),dump(p),dump({'method':'time-decayed Dixon-Coles'}))).lastrowid
def train_player(c,at=None):
 at=at or now(); records=history(c,at); features={}
 for record in records:
  value=historical_lineups(c,record['id'],record['kickoff'])
  if value:features[record['id']]=value
 records=[r for r in records if r['id'] in features]
 if len(records)<40:return None
 model=fit_dixon_coles(records,at,features)
 return c.execute('INSERT INTO models(competition,created_at,cutoff,samples,payload,metrics) VALUES(?,?,?,?,?,?)',(LEAGUE,at,at,len(records),dump(model),dump({'method':'Dixon-Coles + confirmed XI','coverage':len(records)}))).lastrowid
def current_model(c):
 x=c.execute("SELECT * FROM models WHERE competition='E0' AND metrics NOT LIKE '%confirmed XI%' ORDER BY id DESC LIMIT 1").fetchone();return dict(x) if x else None
def current_player_model(c):
 x=c.execute("SELECT * FROM models WHERE competition='E0' AND metrics LIKE '%confirmed XI%' ORDER BY id DESC LIMIT 1").fetchone();return dict(x) if x else None
FIXTURE_WINDOW=timedelta(days=7)
def fixture_window(at=None):
 at=at or now();return at,(datetime.fromisoformat(at)+FIXTURE_WINDOW).isoformat()
def matches(c,upcoming=True,at=None):
 q="SELECT m.*,h.name home_name,a.name away_name FROM matches m JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away WHERE m.competition='E0'"
 if not upcoming:return rows(c,q+' ORDER BY m.kickoff')
 start,end=fixture_window(at)
 return rows(c,q+" AND m.status='scheduled' AND m.kickoff>? AND m.kickoff<=? ORDER BY m.kickoff",(start,end))
def forecast(c,m,at=None):
 at=at or now();model=current_model(c)
 if not model:return None
 # Models are trained against stable canonical team IDs, not display labels.
 p=predict_1x2(json.loads(model['payload']),m['home'],m['away'])
 if not p:return None
 p={**p,'model':'Dixon-Coles'};c.execute('INSERT OR IGNORE INTO predictions(match_id,model_id,created_at,kickoff,payload,features) VALUES(?,?,?,?,?,?)',(m['id'],model['id'],at,m['kickoff'],dump(p),dump({})));return p
def forecast_player(c,m,lineups,captured_at,at=None):
 at=at or now(); model=current_player_model(c)
 if not model:return None
 features={side:lineup_features(c,m['id'],side,lineups[side],m['kickoff']) for side in ('home','away')}
 if not all(features.values()):return None
 prediction=predict_1x2(json.loads(model['payload']),m['home'],m['away'],features)
 if not prediction:return None
 prediction.update({'model':'Dixon-Coles + confirmed XI','lineup_captured_at':captured_at})
 c.execute('INSERT OR IGNORE INTO predictions(match_id,model_id,created_at,kickoff,payload,features) VALUES(?,?,?,?,?,?)',(m['id'],model['id'],at,m['kickoff'],dump(prediction),dump({'variant':'confirmed-xi','captured_at':captured_at,'lineups':features})))
 return prediction
def devig(qs):
 by={q['selection']:q for q in qs}
 if set(by)!={'home','draw','away'}:return {}
 z=sum(1/q['odds'] for q in by.values());return {s:1/q['odds']/z for s,q in by.items()}
def best_market(c,mid):
 qs=rows(c,"SELECT q.* FROM quotes q WHERE q.match_id=? AND q.market='1x2' AND q.verified=1 AND q.id IN (SELECT MAX(id) FROM quotes WHERE match_id=? AND market='1x2' GROUP BY bookmaker,selection)",(mid,mid));groups={}
 for q in qs:groups.setdefault(q['bookmaker'],[]).append(q)
 complete=[g for g in groups.values() if devig(g)];return max(complete,key=lambda g:max(q['quoted_at'] for q in g)) if complete else None
def discrepancies(c,m,p):
 qs=best_market(c,m['id'])
 if not qs:return []
 fair=devig(qs);by={q['selection']:q for q in qs}
 return [dict(selection=s,probability=p['probabilities'][s],odds=by[s]['odds'],bookmaker=by[s]['bookmaker'],quote_time=by[s]['quoted_at'],implied_probability=1/by[s]['odds'],market_probability=fair[s],discrepancy=p['probabilities'][s]-fair[s],edge=p['probabilities'][s]*(by[s]['odds']-1)-(1-p['probabilities'][s]),quote_id=by[s]['id']) for s in ('home','draw','away')]
def account(c):
 bs=rows(c,"SELECT * FROM bets WHERE portfolio='automatic' ORDER BY id DESC");settled=[b for b in bs if b['status'] not in ('open','review')];profit=sum(b['profit'] or 0 for b in settled);reserved=sum(b['stake'] for b in bs if b['status'] in ('open','review'));risked=[b for b in settled if b['status']!='void'];equity=STARTING_BANKROLL;curve=[{'date':'Start','equity':equity}];peak=equity;dd=0
 for b in sorted(settled,key=lambda x:x['settled_at'] or ''):equity+=b['profit'] or 0;peak=max(peak,equity);dd=max(dd,(peak-equity)/peak);curve.append({'date':b['settled_at'],'equity':round(equity,2)})
 return {'balance':round(STARTING_BANKROLL+profit,2),'available':round(STARTING_BANKROLL+profit-reserved,2),'reserved':round(reserved,2),'profit':round(profit,2),'roi':profit/sum(b['stake'] for b in risked) if risked else None,'win_rate':sum(b['status']=='won' for b in risked)/len(risked) if risked else None,'settled':len(risked),'open':sum(b['status'] in ('open','review') for b in bs),'drawdown':dd,'curve':curve,'bets':bs}
def place_required_bet(c,m,p,at=None):
 at=at or now()
 if c.execute("SELECT 1 FROM bets WHERE portfolio='automatic' AND match_id=?",(m['id'],)).fetchone():return 'already placed'
 if not is_bet_day(m['kickoff'],at):return 'blocked: fixture is not being played today'
 choices=discrepancies(c,m,p)
 if not choices:set_setting(c,'blocked:'+m['id'],{'at':at,'reason':'No complete verified 1X2 market'});return 'blocked: odds unavailable'
 x=max(choices,key=lambda x:x['edge']);wallet=account(c);k=max(0,(x['probability']*x['odds']-1)/(x['odds']-1));stake=max(MIN_FALLBACK_STAKE,math.floor(wallet['balance']*k*KELLY_FRACTION*100)/100);stake=min(stake,math.floor(min(wallet['available'],wallet['balance']*MAX_BET_FRACTION)*100)/100)
 if stake<MIN_FALLBACK_STAKE:return 'blocked: bankroll unavailable'
 snap={**x,'model':'Dixon-Coles','staking':{'mode':'fractional-kelly' if k else 'minimum-fallback','bankroll':wallet['balance'],'full_kelly':k}}
 try:c.execute('INSERT INTO bets(portfolio,match_id,quote_id,prediction_id,created_at,stake,snapshot) VALUES(?,?,?,?,?,?,?)',('automatic',m['id'],x['quote_id'],None,at,stake,dump(snap)))
 except sqlite3.IntegrityError:return 'already placed'
 return 'placed'
def settle(at=None):
 at=at or now();n=0
 with connect() as c:
  if os.environ.get('DATABASE_URL'):
   # psycopg starts a transaction for this statement; use the advisory lock
   # instead of issuing a second BEGIN on PostgreSQL.
   c.execute('SELECT pg_advisory_xact_lock(814729301)')
  else:c.execute('BEGIN IMMEDIATE')
  for b in rows(c,"SELECT b.*,m.status match_status,m.stats FROM bets b JOIN matches m ON m.id=b.match_id WHERE b.status IN ('open','review')"):
   if b['match_status']=='cancelled':state='void'
   elif b['match_status']!='finished':continue
   else:
    s=json.loads(b['stats']);state=None if s.get('hg') is None or s.get('ag') is None else ('won' if ('home' if s['hg']>s['ag'] else 'away' if s['ag']>s['hg'] else 'draw')==json.loads(b['snapshot'])['selection'] else 'lost')
   if state is None:c.execute("UPDATE bets SET status='review',reason='Awaiting final score' WHERE id=?",(b['id'],));continue
   odds=json.loads(b['snapshot'])['odds'];profit=round(b['stake']*(odds-1),2) if state=='won' else -b['stake'] if state=='lost' else 0;c.execute('UPDATE bets SET status=?,profit=?,settled_at=?,reason=? WHERE id=?',(state,profit,at,'Verified full-time score',b['id']));n+=1
 return n
