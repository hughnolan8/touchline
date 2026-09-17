"""Public Premier League paper simulation API."""
import json,os
from contextlib import asynccontextmanager
from threading import Lock
from pathlib import Path
import psycopg
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from backend.db import connect,rows,now,setting
from backend.engine import account,matches,forecast,discrepancies,fixture_window,seconds
from .store import configure,initialize,acquire,release
from .engine import refresh_all,refresh_missing_odds
def serialize(b):
 s=json.loads(b['snapshot']);return {'id':b['id'],'home':b['home_name'],'away':b['away_name'],'competition':'Premier League','kickoff':b['kickoff'],'created_at':b['created_at'],'status':b['status'],'stake':b['stake'],'profit':b['profit'],'settled_at':b['settled_at'],'reason':b['reason'],'selection':s['selection'],'odds':s['odds'],'probability':s['probability'],'market_probability':s['market_probability'],'discrepancy':s['discrepancy'],'edge':s['edge'],'bookmaker':s['bookmaker']}
def engine_status(c):
 last=setting(c,'last_engine_success')
 start,end=fixture_window()
 counts={'completed_matches':c.execute("SELECT COUNT(*) FROM matches WHERE competition='E0' AND status='finished'").fetchone()[0],'trained_models':c.execute("SELECT COUNT(*) FROM models WHERE competition='E0'").fetchone()[0],'upcoming_fixtures':c.execute("SELECT COUNT(*) FROM matches WHERE competition='E0' AND status='scheduled' AND kickoff>? AND kickoff<=?",(start,end)).fetchone()[0],'verified_1x2_quotes':c.execute("SELECT COUNT(*) FROM quotes q JOIN matches m ON m.id=q.match_id WHERE m.competition='E0' AND m.kickoff>? AND m.kickoff<=? AND q.market='1x2' AND q.verified=1",(start,end)).fetchone()[0]}
 return {'status':'running' if last and 0<=seconds(now(),last)<=900 else 'overdue','last_success':last,'configured':bool(os.environ.get('MOBILE_ODDS_API_KEY')),'quota':setting(c,'odds_api_quota',{}),'last_manual_refresh':setting(c,'last_manual_refresh'),'league':'Premier League','data':counts}
def recent_form(c,team_id):
 games=rows(c,"SELECT home,away,stats FROM matches WHERE competition='E0' AND status='finished' AND (home=? OR away=?) ORDER BY kickoff DESC LIMIT 5",(team_id,team_id));form=[]
 for game in games:
  score=json.loads(game['stats']);home_goals,away_goals=score.get('hg'),score.get('ag')
  if home_goals is None or away_goals is None:continue
  mine,theirs=(home_goals,away_goals) if game['home']==team_id else (away_goals,home_goals)
  form.append({'result':'W' if mine>theirs else 'L' if mine<theirs else 'D','score':f'{mine}-{theirs}'})
 return form
def create_app(setup=True):
 lock=Lock();app=FastAPI(title='Touchline · Premier League',docs_url=None,redoc_url=None,openapi_url=None)
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
 def health():return {'ok':True,'league':'Premier League','mode':'paper'}
 @app.get('/health/engine')
 def health_engine():
  with connect() as c:return JSONResponse({'ok':engine_status(c)['status']=='running'},200 if engine_status(c)['status']=='running' else 503)
 @app.get('/api/v1/summary')
 def summary():
  with connect() as c:
   a=account(c);bs=rows(c,"SELECT b.*,h.name home_name,a.name away_name,m.kickoff FROM bets b JOIN matches m ON m.id=b.match_id JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away WHERE b.portfolio='automatic' ORDER BY b.id DESC LIMIT 5")
   return {'generated_at':now(),'mode':'paper','account':{k:v for k,v in a.items() if k!='bets'},'engine':engine_status(c),'recent':[serialize(b) for b in bs]}
 @app.get('/api/v1/predictions')
 def predictions():
  with connect() as c:
   answer=[]
   for m in matches(c):
    p=forecast(c,m)
    shadow=c.execute("SELECT payload,features FROM predictions WHERE match_id=? AND features LIKE ? ORDER BY id DESC LIMIT 1",(m['id'],'%confirmed-xi%')).fetchone()
    xi=None
    if shadow:
     player=json.loads(shadow['payload']);features=json.loads(shadow['features'])['lineups'];xi={'status':'confirmed','captured_at':player['lineup_captured_at'],'home':{'adjustment':player['lineup_adjustment']['home'],'contributors':features['home']['starters']},'away':{'adjustment':player['lineup_adjustment']['away'],'contributors':features['away']['starters']}}
    if p:answer.append({'id':m['id'],'home':m['home_name'],'away':m['away_name'],'competition':'Premier League','kickoff':m['kickoff'],'model':'Dixon-Coles','selections':discrepancies(c,m,p),'stats':{'home':{'xg':p['home_goals'],'form':recent_form(c,m['home'])},'away':{'xg':p['away_goals'],'form':recent_form(c,m['away'])},'xi':xi or {'status':'awaiting'}}})
   return answer
 @app.get('/api/v1/bets')
 def bets():
  with connect() as c:
   bs=rows(c,"SELECT b.*,h.name home_name,a.name away_name,m.kickoff FROM bets b JOIN matches m ON m.id=b.match_id JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away WHERE b.portfolio='automatic' ORDER BY b.id DESC")
   return {'items':[serialize(b) for b in bs]}
 @app.get('/api/v1/engine')
 def engine():
  with connect() as c:return engine_status(c)
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
 return app
