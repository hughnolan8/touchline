"""Premier League forecasts, discrepancies, and paper ledger."""
import json,math,os,sqlite3
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from .db import DEFAULT_STRATEGY,connect,rows,now,dump,setting,set_setting
from .models import BASELINE_VERSION,XI_VERSION,fit_dixon_coles,predict_1x2
from .playerstats import historical_lineups, latest_lineup_snapshot, lineup_features
from .app.strategy import Strategy
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
 p=fit_dixon_coles(r,at,version=BASELINE_VERSION)
 if not p:return None
 return c.execute(
  'INSERT INTO models(competition,created_at,cutoff,samples,payload,metrics) VALUES(?,?,?,?,?,?)',
  (LEAGUE, at, at, len(r), dump(p), dump({'method':'time-decayed Dixon-Coles','version':BASELINE_VERSION,'diagnostics':p['diagnostics']})),
 ).lastrowid
def train_player(c,at=None):
 at=at or now(); records=history(c,at); features={}
 for record in records:
  value=historical_lineups(c,record['id'],record['kickoff'])
  if value:features[record['id']]=value
 records=[r for r in records if r['id'] in features]
 if len(records)<40:return None
 model=fit_dixon_coles(records,at,features,version=XI_VERSION,config=setting(c,'xi_model_config'))
 if not model:return None
 return c.execute(
  'INSERT INTO models(competition,created_at,cutoff,samples,payload,metrics) VALUES(?,?,?,?,?,?)',
  (LEAGUE, at, at, len(records), dump(model), dump({'method':'Dixon-Coles + confirmed XI','version':XI_VERSION,'coverage':len(records),'diagnostics':model['diagnostics']})),
 ).lastrowid
def current_model(c):
 x=c.execute("SELECT * FROM models WHERE competition='E0' AND (metrics LIKE ? OR metrics NOT LIKE ?) ORDER BY id DESC LIMIT 1",('%baseline-v1%','%confirmed XI%')).fetchone();return dict(x) if x else None
def current_player_model(c):
 x=c.execute("SELECT * FROM models WHERE competition='E0' AND (metrics LIKE ? OR metrics LIKE ?) ORDER BY id DESC LIMIT 1",('%xi-v2%','%confirmed XI%')).fetchone();return dict(x) if x else None
FIXTURE_WINDOW=timedelta(days=7)
def fixture_window(at=None):
 at=at or now();return at,(datetime.fromisoformat(at)+FIXTURE_WINDOW).isoformat()
def matches(c,upcoming=True,at=None):
 q="SELECT m.*,h.name home_name,a.name away_name FROM matches m JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away WHERE m.competition='E0'"
 if not upcoming:return rows(c,q+' ORDER BY m.kickoff')
 start,end=fixture_window(at)
 return rows(c,q+" AND m.status='scheduled' AND m.kickoff>? AND m.kickoff<=? ORDER BY m.kickoff",(start,end))
def _save_prediction(c,m,model,at,p,features):
 c.execute('INSERT OR IGNORE INTO predictions(match_id,model_id,created_at,kickoff,payload,features) VALUES(?,?,?,?,?,?)',(m['id'],model['id'],at,m['kickoff'],dump(p),dump(features)))
 row=c.execute('SELECT id FROM predictions WHERE match_id=? AND model_id=? AND kickoff=? AND features=?',(m['id'],model['id'],m['kickoff'],dump(features))).fetchone()
 return row[0] if row else None
def forecast(c,m,at=None,version=None):
 at=at or now()
 version=version or setting(c,'strategy',DEFAULT_STRATEGY)['active_model']
 # A confirmed XI is a first-class input to the production forecast.  The
 # baseline remains available when no XI was captured before prediction time.
 snapshot=latest_lineup_snapshot(c,m['id'],at)
 if snapshot and version == XI_VERSION:
  player=forecast_player(c,m,snapshot['lineups'],snapshot['captured_at'],at)
  if player:return player
 if version != BASELINE_VERSION:return None
 model=current_model(c)
 if not model:return None
 # Models are trained against stable canonical team IDs, not display labels.
 p=predict_1x2(json.loads(model['payload']),m['home'],m['away'])
 if not p:return None
 p={**p,'model':'Dixon-Coles','model_version':BASELINE_VERSION};p['prediction_id']=_save_prediction(c,m,model,at,p,{}) ;return p
def forecast_player(c,m,lineups,captured_at,at=None):
 at=at or now(); model=current_player_model(c)
 if not model:return None
 features={side:lineup_features(c,m['id'],side,lineups[side],m['kickoff']) for side in ('home','away')}
 if not all(features.values()):return None
 prediction=predict_1x2(json.loads(model['payload']),m['home'],m['away'],features)
 if not prediction:return None
 prediction.update({'model':'Dixon-Coles + confirmed XI','model_version':XI_VERSION,'lineup_captured_at':captured_at})
 prediction['prediction_id']=_save_prediction(c,m,model,at,prediction,{'variant':'confirmed-xi','captured_at':captured_at,'lineups':features})
 return prediction
def devig(qs):
 by={q['selection']:q for q in qs}
 if set(by)!={'home','draw','away'}:return {}
 z=sum(1/q['odds'] for q in by.values());return {s:1/q['odds']/z for s,q in by.items()}
def fresh_markets(c,mid,at=None,max_quote_age=15):
 at=at or now(); cutoff=(datetime.fromisoformat(at)-timedelta(minutes=max_quote_age)).isoformat()
 qs=rows(c,"SELECT q.* FROM quotes q WHERE q.match_id=? AND q.market='1x2' AND q.verified=1 AND q.id IN (SELECT MAX(id) FROM quotes WHERE match_id=? AND market='1x2' GROUP BY bookmaker,selection)",(mid,mid));groups={}
 for q in qs:groups.setdefault(q['bookmaker'],[]).append(q)
 return [g for g in groups.values() if devig(g) and min(q['quoted_at'] for q in g)>=cutoff]
def best_market(c,mid,at=None,max_quote_age=15):
 books=fresh_markets(c,mid,at,max_quote_age);return max(books,key=lambda g:max(q['quoted_at'] for q in g)) if books else None
def market_snapshot(c,mid,at=None,max_quote_age=15):
 books=fresh_markets(c,mid,at,max_quote_age)
 if not books:return None
 probabilities={s:float(__import__('numpy').median([devig(book)[s] for book in books])) for s in ('home','draw','away')}
 best={s:max((q for book in books for q in book if q['selection']==s),key=lambda q:q['odds']) for s in ('home','draw','away')}
 return {s:{'odds':best[s]['odds'],'bookmaker':best[s]['bookmaker'],'quote_time':best[s]['quoted_at'],'quote_id':best[s]['id'],'market_probability':probabilities[s]} for s in ('home','draw','away')}
def capture_initial_snapshot(c,m,at=None):
 at=at or now();market=market_snapshot(c,m['id'],at)
 if not market:return None
 c.execute('INSERT OR IGNORE INTO fixture_odds_snapshots(match_id,captured_at,payload) VALUES(?,?,?)',(m['id'],at,dump(market)))
 row=c.execute('SELECT captured_at,payload FROM fixture_odds_snapshots WHERE match_id=?',(m['id'],)).fetchone()
 return {'captured_at':row['captured_at'],'selections':json.loads(row['payload'])}
def initial_snapshot(c,mid):
 row=c.execute('SELECT captured_at,payload FROM fixture_odds_snapshots WHERE match_id=?',(mid,)).fetchone()
 return {'captured_at':row['captured_at'],'selections':json.loads(row['payload'])} if row else None
def snapshot_discrepancies(snapshot,p):
 return [dict(selection=s,probability=p['probabilities'][s],odds=x['odds'],bookmaker=x['bookmaker'],quote_time=x['quote_time'],implied_probability=1/x['odds'],market_probability=x['market_probability'],discrepancy=p['probabilities'][s]-x['market_probability'],edge=p['probabilities'][s]*(x['odds']-1)-(1-p['probabilities'][s]),quote_id=x['quote_id']) for s,x in snapshot['selections'].items()]
def discrepancies(c,m,p,at=None,max_quote_age=15):
 market=market_snapshot(c,m['id'],at,max_quote_age)
 return snapshot_discrepancies({'selections':market},p) if market else []
def account(c):
 bs=rows(c,"SELECT * FROM bets WHERE portfolio='automatic' ORDER BY id DESC");settled=[b for b in bs if b['status'] not in ('open','review')];profit=sum(b['profit'] or 0 for b in settled);reserved=sum(b['stake'] for b in bs if b['status'] in ('open','review'));risked=[b for b in settled if b['status']!='void'];equity=STARTING_BANKROLL;curve=[{'date':'Start','equity':equity}];peak=equity;dd=0
 for b in sorted(settled,key=lambda x:x['settled_at'] or ''):equity+=b['profit'] or 0;peak=max(peak,equity);dd=max(dd,(peak-equity)/peak);curve.append({'date':b['settled_at'],'equity':round(equity,2)})
 return {'balance':round(STARTING_BANKROLL+profit,2),'available':round(STARTING_BANKROLL+profit-reserved,2),'reserved':round(reserved,2),'profit':round(profit,2),'roi':profit/sum(b['stake'] for b in risked) if risked else None,'win_rate':sum(b['status']=='won' for b in risked)/len(risked) if risked else None,'settled':len(risked),'open':sum(b['status'] in ('open','review') for b in bs),'drawdown':dd,'curve':curve,'bets':bs}
def record_decision(c,m,p,decision,reason,at,choices=()):
 c.execute('INSERT OR IGNORE INTO decisions(match_id,prediction_id,created_at,model_version,decision,reason,snapshot) VALUES(?,?,?,?,?,?,?)',(m['id'],p.get('prediction_id'),at,p.get('model_version',BASELINE_VERSION),decision,reason,dump({'prediction':p,'choices':choices})))
 return f'{decision}: {reason}'
def place_required_bet(c,m,p,at=None,entry_snapshot=None):
 at=at or now()
 if c.execute("SELECT 1 FROM bets WHERE portfolio='automatic' AND match_id=?",(m['id'],)).fetchone():return 'already placed'
 if not is_bet_day(m['kickoff'],at):return 'blocked: fixture is not being played today'
 strategy=Strategy(**setting(c,'strategy',DEFAULT_STRATEGY))
 if not strategy.enabled:return record_decision(c,m,p,'no_bet','strategy disabled',at)
 choices=snapshot_discrepancies(entry_snapshot,p) if entry_snapshot else discrepancies(c,m,p,at,strategy.max_quote_age)
 if not choices:return record_decision(c,m,p,'no_bet','no fresh complete verified 1X2 market',at)
 x=max(choices,key=lambda x:x['edge']);wallet=account(c)
 if x['edge'] <= 0 or x['edge'] < strategy.min_edge:return record_decision(c,m,p,'no_bet','edge below threshold',at,choices)
 if wallet['reserved']/max(wallet['balance'],1) >= strategy.max_exposure:return record_decision(c,m,p,'no_bet','portfolio exposure cap',at,choices)
 k=max(0,(x['probability']*x['odds']-1)/(x['odds']-1));stake=strategy.stake if strategy.stake_mode=='flat' else math.floor(wallet['balance']*k*strategy.kelly_fraction*100)/100
 stake=max(strategy.min_stake,stake);stake=min(stake,math.floor(min(wallet['available'],wallet['balance']*strategy.max_bet_fraction,wallet['balance']*strategy.max_exposure-wallet['reserved'])*100)/100)
 if stake<strategy.min_stake:return record_decision(c,m,p,'no_bet','bankroll unavailable',at,choices)
 snap={**x,'model':p.get('model','Dixon-Coles'),'model_version':p.get('model_version',BASELINE_VERSION),'staking':{'mode':strategy.stake_mode,'bankroll':wallet['balance'],'full_kelly':k}}
 try:
  inserted=c.execute('INSERT INTO bets(portfolio,match_id,quote_id,prediction_id,created_at,stake,snapshot) VALUES(?,?,?,?,?,?,?)',('automatic',m['id'],x['quote_id'],p.get('prediction_id'),at,stake,dump(snap)))
  c.execute('INSERT OR IGNORE INTO bet_notifications(bet_id) VALUES(?)',(inserted.lastrowid,))
 except sqlite3.IntegrityError:return 'already placed'
 return 'placed'
def capture_closing_line(c,b,at=None):
 """Attach the final available best-market line to one paper bet."""
 at=at or now()
 if c.execute('SELECT 1 FROM bet_closing_lines WHERE bet_id=?',(b['id'],)).fetchone():return False
 market=market_snapshot(c,b['match_id'],at)
 if not market:return False
 selection=json.loads(b['snapshot'])['selection'];close=market[selection];entry=json.loads(b['snapshot'])['odds']
 clv=1/close['odds']-1/entry
 c.execute('INSERT OR IGNORE INTO bet_closing_lines(bet_id,quote_id,captured_at,odds,bookmaker,quoted_at,clv) VALUES(?,?,?,?,?,?,?)',(b['id'],close['quote_id'],at,close['odds'],close['bookmaker'],close['quote_time'],clv))
 return True
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
