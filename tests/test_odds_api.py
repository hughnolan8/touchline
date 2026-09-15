from backend.mobile.engine import select_automatic as auto_bet
import json
import os
from datetime import datetime,timedelta,timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.db import connect,now,setting,set_setting,dump
from backend.odds_api import OddsApiError,parse_events,SPORTS
from backend.engine import size_stake,portfolios,opportunities
from test_engine import seed,shift


def event():
    return {'id':'api-event-123','sport_key':'soccer_epl','home_team':'Arsenal','away_team':'Chelsea','commence_time':shift(30),'bookmakers':[{'key':'williamhill','title':'William Hill','last_update':shift(-1),'link':'https://sports.williamhill.com/','markets':[{'key':'h2h','outcomes':[{'name':'Arsenal','price':2.1},{'name':'Draw','price':3.4},{'name':'Chelsea','price':3.5}]},{'key':'totals','last_update':shift(-.5),'outcomes':[{'name':'Over','price':1.9,'point':2.5},{'name':'Under','price':1.95,'point':2.5}]}]}]}

def mock_client(handler):return httpx.Client(transport=httpx.MockTransport(handler))

def test_api_mapping_and_stable_reimport():
    e=event()
    with connect() as c:
        assert parse_events(c,[e],'E0',now())==1
        assert parse_events(c,[e],'E0',now())==1
        assert c.execute('SELECT COUNT(*) FROM matches').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM quotes').fetchone()[0]==5
        m=dict(c.execute('SELECT * FROM matches').fetchone());assert m['time_confirmed']==1
        q=dict(c.execute("SELECT * FROM quotes WHERE market='goals' LIMIT 1").fetchone());assert q['line']==2.5 and q['verified']==1 and q['bookmaker']=='William Hill'
        assert q['quoted_at']!=q['collected_at']

def test_exchanges_and_live_events_are_excluded():
    e=event();e['bookmakers'][0]['key']='betfair_ex_uk'
    live=event();live['id']='live';live['commence_time']=shift(-1)
    with connect() as c:
        assert parse_events(c,[live,e],'E0',now())==1
        assert c.execute('SELECT COUNT(*) FROM quotes').fetchone()[0]==0

def test_unexpected_competition_and_invalid_price_quarantine():
    e=event();e['sport_key']='soccer_spain_la_liga'
    bad=event();bad['bookmakers'][0]['markets'][0]['outcomes'][0]['price']=float('inf')
    # JSON provider would never legally emit Infinity; parser must still reject it without DB contamination.
    bad['bookmakers'][0]['markets'][0]['outcomes'][0]['price']='Infinity'
    with connect() as c:
        assert parse_events(c,[e,bad],'E0',now())==0
        assert c.execute('SELECT COUNT(*) FROM quotes').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM quarantine').fetchone()[0]==2






def test_kelly_scales_with_edge_and_caps_risk():
    config={'stake_mode':'kelly','kelly_fraction':.25,'max_bet_fraction':.02,'max_exposure':.1,'min_stake':1,'stake':10}
    account={'balance':1000,'available':1000,'reserved':0}
    small=size_stake({'probability':.52,'odds':2},account,config)
    large=size_stake({'probability':.6,'odds':2},account,config)
    assert small['stake']==10 and large['stake']==20
    assert size_stake({'probability':.501,'odds':2},account,config)['stake']==0
    assert size_stake({'probability':.4,'odds':2},account,config)['stake']==0
    assert size_stake({'probability':.6,'odds':2},{'balance':1000,'available':905,'reserved':95},config)['stake']==5

def test_push_aware_kelly():
    config={'stake_mode':'kelly','kelly_fraction':.25,'max_bet_fraction':.1,'max_exposure':.5,'min_stake':1,'stake':10}
    result=size_stake({'probability':.5,'odds':2,'push':.2},{'balance':1000,'available':1000,'reserved':0},config)
    assert result['full_kelly']==pytest.approx(.25)
    assert result['stake']==62.5

def test_auto_ledger_locks_kelly_calculation():
    seed()
    with connect() as c:
        cfg=setting(c,'strategy');cfg['stake_mode']='kelly';set_setting(c,'strategy',cfg)
    assert auto_bet()==1 and auto_bet()==0
    with connect() as c:
        p=portfolios(c)[0];assert p['reserved']==20
        assert p['bets'][0]['snapshot']['staking']['mode']=='kelly'
        assert p['bets'][0]['snapshot']['staking']['bankroll']==1000
