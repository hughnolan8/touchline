"""One five-minute Premier League worker; no queue or trainer service."""
import logging
from backend.db import connect,now,setting,set_setting
from backend.engine import best_market,matches,train,train_player,forecast,place_required_bet,settle,seconds
from backend.playerstats import latest_lineup_snapshot
from backend.understat import season_start,sync_epl_seasons
from .provider import MobileOdds
from .fotmob import FotMobLineups
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
 with connect() as c:train(c,at);train_player(c,at);upcoming=matches(c,at=at)
 odds=MobileOdds()
 try:count=odds.refresh(upcoming,at)
 finally:odds.close()
 with connect() as c:
  placed=[]
  for m in upcoming:
   # A manual refresh is never allowed to bypass the confirmed-XI gate.
   if not latest_lineup_snapshot(c,m['id'],at):
    placed.append('blocked: confirmed lineup unavailable');continue
   p=forecast(c,m,at)
   placed.append(place_required_bet(c,m,p,at) if p and p.get('model')=='Dixon-Coles + confirmed XI' else 'blocked: player model unavailable')
  set_setting(c,'last_manual_refresh',at)
 result={'fixtures':count,'decisions':placed,'settled':settle(at)}
 logging.info('manual_refresh fixtures=%s decisions=%s settled=%s',count,len(placed),result['settled'])
 return result
def refresh_missing_odds(at=None):
 at=at or now()
 with connect() as c:
  missing=[m for m in matches(c,at=at) if not best_market(c,m['id'])]
 if not missing:return {'requested':0,'fixtures':0,'still_missing':0}
 odds=MobileOdds()
 try:count=odds.refresh(missing,at)
 finally:odds.close()
 with connect() as c:
  remaining=sum(not bool(best_market(c,m['id'])) for m in missing)
  set_setting(c,'last_missing_odds_refresh',at)
 return {'requested':len(missing),'fixtures':count,'still_missing':remaining}
def tick(at=None):
 at=at or now();token=acquire('engine',seconds=290)
 if not token:return {'ok':True,'skipped':True}
 try:
  bootstrap(at)
  # Results are refreshed every cycle only when an open fixture has finished/overdue.
  with connect() as c:open_bets=c.execute("SELECT 1 FROM bets b JOIN matches m ON m.id=b.match_id WHERE b.status IN ('open','review') AND m.kickoff<=?",(at,)).fetchone()
  if open_bets:import_scores(at)
  with connect() as c:
   due=[m for m in matches(c,at=at) if 55<=seconds(m['kickoff'],at)/60<=60 and setting(c,'refreshed:'+m['id']) is None]
  if due:
   odds=MobileOdds()
   try:odds.refresh(due,at)
   finally:odds.close()
   with connect() as c:
    train(c,at);train_player(c,at)
    for m in due:
     p=forecast(c,m,at)
     result=place_required_bet(c,m,p,at) if p else 'blocked: model unavailable'
     set_setting(c,'refreshed:'+m['id'],{'at':at,'result':result})
  # FotMob typically publishes official XIs about 30 minutes before kickoff.
  # Do not mark a fixture complete unless a valid 11-versus-11 snapshot was
  # saved; a subsequent five-minute cycle can retry while the window remains.
  with connect() as c:
   lineup_due=[m for m in matches(c,at=at) if 25<=seconds(m['kickoff'],at)/60<=30 and setting(c,'lineup-refreshed:'+m['id']) is None]
  captured=[]
  if lineup_due:
   lineups=FotMobLineups()
   try:captured=lineups.refresh(lineup_due,at)
   finally:lineups.close()
  if captured:
   selected=[m for m in lineup_due if m['id'] in captured]
   odds=MobileOdds()
   try:odds.refresh(selected,at)
   finally:odds.close()
   with connect() as c:
    train(c,at);train_player(c,at)
    for m in selected:
     p=forecast(c,m,at)
     result=place_required_bet(c,m,p,at) if p and p.get('model')=='Dixon-Coles + confirmed XI' else 'blocked: player model unavailable'
     set_setting(c,'lineup-refreshed:'+m['id'],{'at':at,'result':result})
  settled=settle(at)
  with connect() as c:set_setting(c,'last_engine_success',at)
  return {'ok':True,'refreshed':len(due),'lineups':len(captured),'settled':settled}
 finally:release('engine',token)
