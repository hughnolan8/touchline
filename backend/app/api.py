"""Public multi-league paper simulation API."""
import json
import hmac
import os
from contextlib import asynccontextmanager
from threading import Lock
from pathlib import Path
import psycopg
from fastapi import FastAPI,HTTPException,Header
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from backend.db import connect,rows,now,setting
from backend.engine import account,matches,forecast,discrepancies,fixture_window,seconds,initial_snapshot,snapshot_discrepancies
from backend.competitions import COMPETITIONS, BY_CODE, name
from .store import configure,initialize,acquire,release
from .engine import refresh_all,refresh_missing_odds,tick
from .engine import refresh_all,refresh_missing_odds
from .provider import odds_api_configured
def serialize(b):
 s=json.loads(b['snapshot']);closing=None
 if b.get('closing_odds') is not None:
  closing={'odds':b['closing_odds'],'bookmaker':b['closing_bookmaker'],'quote_time':b['closing_quote_time'],'captured_at':b['closing_captured_at'],'clv':b['closing_clv']}
 return {'id':b['id'],'home':b['home_name'],'away':b['away_name'],'competition':name(b['competition']),'competition_code':b['competition'],'kickoff':b['kickoff'],'created_at':b['created_at'],'status':b['status'],'stake':b['stake'],'profit':b['profit'],'settled_at':b['settled_at'],'reason':b['reason'],'selection':s['selection'],'odds':s['odds'],'probability':s['probability'],'market_probability':s['market_probability'],'discrepancy':s['discrepancy'],'edge':s['edge'],'bookmaker':s['bookmaker'],'entry_quote_time':s['quote_time'],'closing_line':closing}
BET_QUERY="""SELECT b.*,h.name home_name,a.name away_name,m.kickoff,m.competition,
 cl.odds closing_odds,cl.bookmaker closing_bookmaker,cl.quoted_at closing_quote_time,
 cl.captured_at closing_captured_at,cl.clv closing_clv
 FROM bets b JOIN matches m ON m.id=b.match_id JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away
 LEFT JOIN bet_closing_lines cl ON cl.bet_id=b.id WHERE b.portfolio='automatic'"""
def _league(value):
 if value is not None and value not in BY_CODE:raise HTTPException(422,'Unsupported league')
 return value
def engine_status(c,league=None):
 league=_league(league);where=' AND competition=?' if league else '';args=(league,) if league else ()
 last=setting(c,'last_engine_success')
 start,end=fixture_window()
 counts={'completed_matches':c.execute(f"SELECT COUNT(*) FROM matches WHERE status='finished'{where}",args).fetchone()[0],'trained_models':c.execute(f"SELECT COUNT(*) FROM models WHERE 1=1{where}",args).fetchone()[0],'upcoming_fixtures':c.execute(f"SELECT COUNT(*) FROM matches WHERE status='scheduled' AND kickoff>? AND kickoff<=?{where}",(start,end,*args)).fetchone()[0],'verified_1x2_quotes':c.execute(f"SELECT COUNT(*) FROM quotes q JOIN matches m ON m.id=q.match_id WHERE m.kickoff>? AND m.kickoff<=? AND q.market='1x2' AND q.verified=1{where}",(start,end,*args)).fetchone()[0]}
 return {'status':'running' if last and 0<=seconds(now(),last)<=900 else 'overdue','last_success':last,'configured':odds_api_configured() and setting(c,'odds_api_engine_configured') is True,'quota':setting(c,'odds_api_quota',{}),'last_manual_refresh':setting(c,'last_manual_refresh'),'leagues':[{'code':x.code,'name':x.name} for x in COMPETITIONS],'selected_league':league,'data':counts}
def recent_form(c,team_id,league):
 games=rows(c,"SELECT home,away,stats FROM matches WHERE competition=? AND status='finished' AND (home=? OR away=?) ORDER BY kickoff DESC LIMIT 5",(league,team_id,team_id));form=[]
 for game in games:
  score=json.loads(game['stats']);home_goals,away_goals=score.get('hg'),score.get('ag')
  if home_goals is None or away_goals is None:continue
  mine,theirs=(home_goals,away_goals) if game['home']==team_id else (away_goals,home_goals)
  form.append({'result':'W' if mine>theirs else 'L' if mine<theirs else 'D','score':f'{mine}-{theirs}'})
 return form
def create_app(setup=True):
 lock=Lock();app=FastAPI(title='Touchline',docs_url=None,redoc_url=None,openapi_url=None)
 def ready():
  with lock:
   if getattr(app.state,'ready',False):return True
   try:initialize();app.state.ready=True;return True
   except psycopg.OperationalError:return False
 @asynccontextmanager
 async def lifespan(_):
  if setup:configure()
  await run_in_threadpool(ready);yield
 app.router.lifespan_context=lifespan;root=Path(__file__).resolve().parents[2]/'web';app.mount('/static',StaticFiles(directory=root/'static'),name='static')
 @app.middleware('http')
 async def db(request,call_next):
  if request.url.path=='/' or request.url.path.startswith('/static/'):return await call_next(request)
  if not await run_in_threadpool(ready):return JSONResponse({'detail':'Database unavailable'},503)
  return await call_next(request)
 @app.get('/',include_in_schema=False)
 def dashboard():return FileResponse(root/'index.html')
 @app.get('/health')
 def health():return {'ok':True,'leagues':[{'code':x.code,'name':x.name} for x in COMPETITIONS],'mode':'paper'}
 @app.get('/health/engine')
 def health_engine():
  with connect() as c:return JSONResponse({'ok':engine_status(c)['status']=='running'},200 if engine_status(c)['status']=='running' else 503)
 @app.get('/api/v1/summary')
 def summary(league:str|None=None):
  league=_league(league)
  with connect() as c:
   a=account(c);suffix=' AND m.competition=?' if league else '';bs=rows(c,BET_QUERY+suffix+' ORDER BY b.id DESC LIMIT 5',(league,) if league else ())
   return {'generated_at':now(),'mode':'paper','account':{k:v for k,v in a.items() if k!='bets'},'engine':engine_status(c,league),'recent':[serialize(b) for b in bs]}
 @app.get('/api/v1/predictions')
 def predictions(league:str|None=None):
  league=_league(league)
  with connect() as c:
   answer=[]
   for m in matches(c,league=league):
    p=forecast(c,m)
    decision=c.execute('SELECT decision,reason,model_version FROM decisions WHERE match_id=? ORDER BY id DESC LIMIT 1',(m['id'],)).fetchone()
    shadow=c.execute("SELECT payload,features FROM predictions WHERE match_id=? AND features LIKE ? ORDER BY id DESC LIMIT 1",(m['id'],'%confirmed-xi%')).fetchone()
    xi=None
    if shadow:
     player=json.loads(shadow['payload']);features=json.loads(shadow['features'])['lineups'];xi={'status':'confirmed','captured_at':player['lineup_captured_at'],'home':{'adjustment':player['lineup_adjustment']['home'],'contributors':features['home']['starters']},'away':{'adjustment':player['lineup_adjustment']['away'],'contributors':features['away']['starters']}}
    if p:
     entry=initial_snapshot(c,m['id'])
     answer.append({'id':m['id'],'home':m['home_name'],'away':m['away_name'],'competition':name(m['competition']),'competition_code':m['competition'],'kickoff':m['kickoff'],'model':p['model'],'model_version':p.get('model_version'),'forecast_status':'ready','decision':dict(decision) if decision else None,'selections':snapshot_discrepancies(entry,p) if entry else discrepancies(c,m,p),'initial_odds_captured_at':entry['captured_at'] if entry else None,'stats':{'home':{'xg':p['home_goals'],'form':recent_form(c,m['home'],m['competition'])},'away':{'xg':p['away_goals'],'form':recent_form(c,m['away'],m['competition'])},'xi':xi or {'status':'awaiting'}}})
   return answer
 @app.get('/api/v1/bets')
 def bets(league:str|None=None):
  league=_league(league)
  with connect() as c:
   bs=rows(c,BET_QUERY+(' AND m.competition=?' if league else '')+' ORDER BY b.id DESC',(league,) if league else ())
   return {'items':[serialize(b) for b in bs]}
 @app.get('/api/v1/engine')
 def engine(league:str|None=None):
  with connect() as c:return engine_status(c,league)
 @app.post('/api/v1/refresh-all')
 def refresh_all_endpoint():
  token=acquire('manual-refresh',seconds=300)
  if not token:raise HTTPException(409,'A refresh is already running')
  try:return refresh_all()
  finally:release('manual-refresh',token)
 @app.post('/api/v1/refresh-missing-odds')
 def refresh_missing_odds_endpoint():
  token=acquire('missing-odds-refresh',seconds=300)
  if not token:raise HTTPException(409,'An odds refresh is already running')
  try:return refresh_missing_odds()
  finally:release('missing-odds-refresh',token)
 @app.post('/api/v1/refresh-engine')
 def refresh_engine_endpoint(x_deployment_refresh_token:str|None=Header(default=None)):
  token=os.environ.get('TOUCHLINE_DEPLOY_REFRESH_TOKEN')
  if not token or not x_deployment_refresh_token or not hmac.compare_digest(token,x_deployment_refresh_token):raise HTTPException(404)
  result=tick()
  if result.get('skipped'):raise HTTPException(409,'An engine refresh is already running')
  return result
 return app
