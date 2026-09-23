"""One five-minute Premier League worker; no queue or trainer service."""
import logging
from backend.db import connect,now,setting,set_setting
from backend.engine import BASELINE_VERSION,XI_VERSION,best_market,matches,train,train_player,forecast,place_required_bet,settle,seconds,capture_initial_snapshot,initial_snapshot,capture_closing_line
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
   baseline=forecast(c,m,at,BASELINE_VERSION)
   candidate=forecast(c,m,at,XI_VERSION)
   active=setting(c,'strategy',{}).get('active_model',BASELINE_VERSION)
   p=candidate if active==XI_VERSION else baseline
   placed.append(place_required_bet(c,m,p,at) if p else 'blocked: active model unavailable')
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
def _capture_lineups(fixtures,at):
 if not fixtures:return []
 lineups=FotMobLineups()
 try:return lineups.refresh(fixtures,at)
 finally:lineups.close()
def _place_confirmed(fixtures,captured,at):
 if not captured:return []
 selected=[m for m in fixtures if m['id'] in captured]
 with connect() as c:
  train(c,at);train_player(c,at);results=[]
  for m in selected:
   snapshot=initial_snapshot(c,m['id'])
   if not snapshot:
    results.append('blocked: initial odds unavailable');continue
   # Persist both forecasts for validation. The active version controls the
   # paper decision while the other remains a shadow forecast.
   baseline=forecast(c,m,at,BASELINE_VERSION);candidate=forecast(c,m,at,XI_VERSION)
   active=setting(c,'strategy',{}).get('active_model',BASELINE_VERSION)
   p=candidate if active==XI_VERSION else baseline
   result=place_required_bet(c,m,p,at,entry_snapshot=snapshot) if p else 'blocked: active model unavailable'
   set_setting(c,'lineup-refreshed:'+m['id'],{'at':at,'result':result})
   results.append(result)
 return results
def tick(at=None):
 at=at or now();token=acquire('engine',seconds=290)
 if not token:return {'ok':True,'skipped':True}
 try:
  bootstrap(at)
  # Results are refreshed every cycle only when an open fixture has finished/overdue.
  with connect() as c:open_bets=c.execute("SELECT 1 FROM bets b JOIN matches m ON m.id=b.match_id WHERE b.status IN ('open','review') AND m.kickoff<=?",(at,)).fetchone()
  if open_bets:import_scores(at)
  # The initial entry market is captured once in the 55-60 minute window.
  # It remains the paper-bet price even if the confirmed XI arrives later.
  with connect() as c:
   due=[m for m in matches(c,at=at) if 55<=seconds(m['kickoff'],at)/60<=60 and setting(c,'initial-odds-refreshed:'+m['id']) is None]
  if due:
   odds=MobileOdds()
   try:odds.refresh(due,at)
   finally:odds.close()
   with connect() as c:
    for m in due:
     snapshot=capture_initial_snapshot(c,m,at)
     set_setting(c,'initial-odds-refreshed:'+m['id'],{'at':at,'result':'captured' if snapshot else 'no fresh complete market'})
  # Poll for the XI at the entry window, then retry through the 30 minute
  # cutoff. Prices are deliberately not refreshed during those retries.
  with connect() as c:
   lineup_due=[m for m in matches(c,at=at) if initial_snapshot(c,m['id']) and setting(c,'lineup-refreshed:'+m['id']) is None and 30<=seconds(m['kickoff'],at)/60<=60]
  captured=_capture_lineups(lineup_due,at)
  _place_confirmed(lineup_due,captured,at)
  # A final refresh in the last five minutes establishes the market close.
  with connect() as c:
   closing_due=[]
   for m in matches(c,at=at):
    if not 0<seconds(m['kickoff'],at)/60<=5:continue
    bet=c.execute("SELECT id FROM bets WHERE portfolio='automatic' AND match_id=?",(m['id'],)).fetchone()
    if bet and not c.execute('SELECT 1 FROM bet_closing_lines WHERE bet_id=?',(bet['id'],)).fetchone():closing_due.append(m)
  closed=0
  if closing_due:
   odds=MobileOdds()
   try:odds.refresh(closing_due,at)
   finally:odds.close()
   with connect() as c:
    for m in closing_due:
     bet=dict(c.execute("SELECT * FROM bets WHERE portfolio='automatic' AND match_id=?",(m['id'],)).fetchone())
     if capture_closing_line(c,bet,at):
      closed+=1;set_setting(c,'closing-refreshed:'+m['id'],{'at':at,'result':'captured'})
  settled=settle(at)
  with connect() as c:set_setting(c,'last_engine_success',at)
  return {'ok':True,'refreshed':len(due),'lineups':len(captured),'closed':closed,'settled':settled}
 finally:release('engine',token)
