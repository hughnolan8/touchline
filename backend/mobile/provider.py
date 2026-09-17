"""Minimal quota-aware Premier League odds collection."""
import os,httpx,logging
from datetime import datetime,timedelta
from backend.db import connect,now,setting,set_setting,dump
from backend.odds_api import OddsApiError,SPORT,parse_events
class MobileOdds:
 def __init__(self):self.client=httpx.Client(timeout=25)
 def close(self):self.client.close()
 def refresh(self,at=None,from_time=None,to_time=None):
  key=os.environ.get('MOBILE_ODDS_API_KEY')
  if not key:raise OddsApiError('MOBILE_ODDS_API_KEY is not configured')
  at=datetime.fromisoformat(at or now());params={'apiKey':key,'regions':'uk','markets':'h2h','oddsFormat':'decimal','dateFormat':'iso'}
  # The Odds API permits at most three days per filtered request. Keep the
  # dashboard's seven-day horizon by collecting it in supported chunks.
  start=datetime.fromisoformat(from_time) if from_time else at
  end=datetime.fromisoformat(to_time) if to_time else at+timedelta(days=7)
  events=[];last_response=None;cursor=start
  try:
   while cursor<end:
    stop=min(cursor+timedelta(days=3),end)
    response=self.client.get(f'https://api.the-odds-api.com/v4/sports/{SPORT}/odds',params={**params,'commenceTimeFrom':cursor.isoformat(),'commenceTimeTo':stop.isoformat()});response.raise_for_status()
    events.extend(response.json());last_response=response;cursor=stop
  except (httpx.HTTPError,ValueError):raise OddsApiError('Odds API request failed') from None
  observed=now()
  with connect() as c:
   count=parse_events(c,events,observed);set_setting(c,'odds_api_quota',{'remaining':last_response.headers.get('x-requests-remaining'),'checked_at':observed});set_setting(c,'last_odds_refresh',observed)
  logging.info('odds_refresh events=%s fixtures=%s',len(events),count)
  return count
