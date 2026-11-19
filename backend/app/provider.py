"""Quota-aware, fixture-specific supported-league odds collection."""
import logging,os
from datetime import datetime,timezone

import httpx

from backend.db import connect,now,set_setting,setting
from backend.odds_api import OddsApiError,parse_events
from backend.competitions import competition
from backend.providers import canonical
from .store import transaction


def odds_api_key():
 return os.environ.get('TOUCHLINE_ODDS_API_KEY') or os.environ.get('MOBILE_ODDS_API_KEY')


def odds_api_configured():
 return bool(odds_api_key())


def reserve_request(at):
 cap=os.environ.get('TOUCHLINE_ODDS_MAX_REQUESTS_PER_UTC_DAY')
 if cap is None:return
 try:cap=int(cap)
 except ValueError:raise OddsApiError('TOUCHLINE_ODDS_MAX_REQUESTS_PER_UTC_DAY must be a positive integer') from None
 if cap<1:raise OddsApiError('TOUCHLINE_ODDS_MAX_REQUESTS_PER_UTC_DAY must be a positive integer')
 day=datetime.fromisoformat(at.replace('Z','+00:00')).astimezone(timezone.utc).date().isoformat()
 with transaction() as c:
  key=f'odds_api_requests:{day}';used=setting(c,key,0)
  if used>=cap:raise OddsApiError(f'Odds API daily request limit reached ({cap})')
  set_setting(c,key,used+1)


class MobileOdds:
 def __init__(self):self.client=httpx.Client(timeout=25)
 def close(self):self.client.close()
 def _get(self,sport,path=None,params=None,at=None):
  if at is None: sport,path,params,at='soccer_epl',sport,path,params
  reserve_request(at)
  try:
   response=self.client.get(f'https://api.the-odds-api.com/v4/sports/{sport}{path}',params=params);response.raise_for_status()
   return response.json(),response
  except (httpx.HTTPError,ValueError):raise OddsApiError('Odds API request failed') from None
 def refresh(self,fixtures,at=None):
  key=odds_api_key()
  if not odds_api_configured():raise OddsApiError('TOUCHLINE_ODDS_API_KEY is not configured')
  at=at or now();base={'apiKey':key,'dateFormat':'iso'};count=0;matched=0;response=None
  for league in {fixture['competition'] for fixture in fixtures}:
   info=competition(league);events,response=self._get(info.odds_sport,'/events',base,at);wanted=[]
   with connect() as c:
    for event in events:
     try:
      home=canonical(c,'the-odds-api',event['home_team']);away=canonical(c,'the-odds-api',event['away_team']);kickoff=datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))
      if any(m['competition']==league and m['home']==home and m['away']==away and abs((datetime.fromisoformat(m['kickoff'])-kickoff).total_seconds())<172800 for m in fixtures):wanted.append(event['id'])
     except (KeyError,TypeError,ValueError):continue
   payloads=[]
   for event_id in wanted:
    payload,response=self._get(info.odds_sport,f'/events/{event_id}/odds',{**base,'regions':'uk','markets':'h2h','oddsFormat':'decimal'},at)
    payload.setdefault('sport_key',info.odds_sport);payloads.append(payload)
   observed=now()
   with connect() as c:count+=parse_events(c,payloads,observed,league)
   matched+=len(wanted)
  observed=now()
  with connect() as c:
   set_setting(c,'odds_api_quota',{'remaining':response.headers.get('x-requests-remaining') if response else None,'checked_at':observed});set_setting(c,'last_odds_refresh',observed)
  logging.info('odds_refresh requested=%s matched=%s fixtures=%s',len(fixtures),matched,count)
  return count
