"""One five-minute Premier League worker; no queue or trainer service."""
import logging
from backend.db import connect,now,setting,set_setting
from backend.engine import matches,train,forecast,place_required_bet,settle,seconds
from backend.understat import season_start,sync_epl_seasons
from .provider import MobileOdds
from .store import acquire,release
def import_scores(at=None):
 at=at or now()
 with connect() as c:
  count=sync_epl_seasons(c,[season_start(at)])
 logging.info('understat_refresh records=%s',count)
 return count
def bootstrap(at=None):
 at=at or now()
 with connect() as c:
  if setting(c,'bootstrap_complete'):return False
 year=season_start(at)
 with connect() as c:
  sync_epl_seasons(c,range(year-3,year+1))
 with connect() as c:set_setting(c,'bootstrap_complete',at)
 return True
def refresh_all(at=None):
 at=at or now();bootstrap(at);import_scores(at)
 with connect() as c:
  train(c,at)
 odds=MobileOdds()
 try:count=odds.refresh(at)
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
   try:odds.refresh(at)
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
