"""One five-minute Premier League worker; no queue or trainer service."""
from datetime import datetime,timedelta
import logging
from backend.db import connect,now,setting,set_setting
from backend.engine import matches,train,forecast,place_required_bet,settle,seconds
from backend.providers import PublicFiles,football_csv
from .provider import MobileOdds
from .store import acquire,release
def season_url(at,year=None):
 dt=datetime.fromisoformat(at);year=year if year is not None else (dt.year if dt.month>=7 else dt.year-1);return f'https://www.football-data.co.uk/mmz4281/{year%100:02}{(year+1)%100:02}/E0.csv'
def import_scores(at=None):
 at=at or now();provider=PublicFiles()
 try:
  with connect() as c:
   count=provider.fetch(c,season_url(at),'football-data',football_csv)
  logging.info('score_refresh records=%s',count)
  return count
 finally:provider.client.close()
def bootstrap(at=None):
 at=at or now()
 with connect() as c:
  if setting(c,'bootstrap_complete'):return False
 year=datetime.fromisoformat(at).year if datetime.fromisoformat(at).month>=7 else datetime.fromisoformat(at).year-1
 provider=PublicFiles()
 try:
  with connect() as c:
   for y in range(year-3,year+1):provider.fetch(c,season_url(at,y),'football-data',football_csv)
 finally:provider.client.close()
 with connect() as c:set_setting(c,'bootstrap_complete',at)
 return True
def refresh_all(at=None):
 at=at or now();bootstrap(at);import_scores(at)
 with connect() as c:
  train(c,at)
 odds=MobileOdds()
 try:count=odds.refresh()
 finally:odds.close()
 with connect() as c:
  placed=[]
  for m in matches(c):
   p=forecast(c,m,at)
   if p:placed.append(place_required_bet(c,m,p,at))
  set_setting(c,'last_manual_refresh',at)
 result={'fixtures':count,'decisions':placed,'settled':settle(at)}
 logging.info('manual_refresh fixtures=%s decisions=%s settled=%s',count,len(placed),result['settled'])
 return result
def tick(at=None):
 at=at or now();token=acquire('engine',seconds=290)
 if not token:return {'ok':True,'skipped':True}
 try:
  bootstrap(at)
  # Results are refreshed every cycle only when an open fixture has finished/overdue.
  with connect() as c:open_bets=c.execute("SELECT 1 FROM bets b JOIN matches m ON m.id=b.match_id WHERE b.status IN ('open','review') AND m.kickoff<=?",(at,)).fetchone()
  if open_bets:import_scores(at)
  with connect() as c:
   due=[m for m in matches(c) if 55<=seconds(m['kickoff'],at)/60<=60 and setting(c,'refreshed:'+m['id']) is None]
  if due:
   odds=MobileOdds()
   try:odds.refresh()
   finally:odds.close()
   with connect() as c:
    train(c,at)
    for m in due:
     p=forecast(c,m,at)
     result=place_required_bet(c,m,p,at) if p else 'blocked: model unavailable'
     set_setting(c,'refreshed:'+m['id'],{'at':at,'result':result})
  settled=settle(at)
  with connect() as c:set_setting(c,'last_engine_success',at)
  return {'ok':True,'refreshed':len(due),'settled':settled}
 finally:release('engine',token)
