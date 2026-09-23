"""Quota-aware, fixture-specific Premier League odds collection."""
import logging,os
from datetime import datetime

import httpx

from backend.db import connect,now,set_setting
from backend.odds_api import OddsApiError,SPORT,parse_events
from backend.providers import canonical


class MobileOdds:
 def __init__(self):self.client=httpx.Client(timeout=25)
 def close(self):self.client.close()
 def _get(self,path,params):
  try:
   response=self.client.get(f'https://api.the-odds-api.com/v4/sports/{SPORT}{path}',params=params);response.raise_for_status()
   return response.json(),response
  except (httpx.HTTPError,ValueError):raise OddsApiError('Odds API request failed') from None
 def refresh(self,fixtures,at=None):
  key=os.environ.get('TOUCHLINE_ODDS_API_KEY') or os.environ.get('MOBILE_ODDS_API_KEY')
  if not key:raise OddsApiError('TOUCHLINE_ODDS_API_KEY is not configured')
  at=at or now();base={'apiKey':key,'dateFormat':'iso'}
  events,response=self._get('/events',base)
  wanted=[]
  with connect() as c:
   for event in events:
    try:
     home=canonical(c,'the-odds-api',event['home_team']);away=canonical(c,'the-odds-api',event['away_team']);kickoff=datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))
     if any(m['home']==home and m['away']==away and abs((datetime.fromisoformat(m['kickoff'])-kickoff).total_seconds())<172800 for m in fixtures):wanted.append(event['id'])
    except (KeyError,TypeError,ValueError):continue
  payloads=[]
  for event_id in wanted:
   payload,response=self._get(f'/events/{event_id}/odds',{**base,'regions':'uk','markets':'h2h','oddsFormat':'decimal'})
   payload.setdefault('sport_key',SPORT);payloads.append(payload)
  observed=now()
  with connect() as c:
   count=parse_events(c,payloads,observed);set_setting(c,'odds_api_quota',{'remaining':response.headers.get('x-requests-remaining'),'checked_at':observed});set_setting(c,'last_odds_refresh',observed)
  logging.info('odds_refresh requested=%s matched=%s fixtures=%s',len(fixtures),len(wanted),count)
  return count
