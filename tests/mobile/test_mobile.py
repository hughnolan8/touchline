import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.db import connect, now, setting, set_setting, dump
from backend.mobile.api import create_app
from backend.mobile.store import initialize, acquire, release, configure, transaction
from backend.mobile.engine import select_automatic, schedule, claim, complete, tick
from backend.mobile.provider import MobileOdds, ingest_scores
from backend.odds_api import OddsApiError
from backend.providers import ingest_match, add_quote
from backend.engine import settle, portfolios

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('MOBILE_OWNER_TOKEN', 'o' * 40)
    with TestClient(create_app(setup=False)) as c:
        yield c

OWNER = {'Authorization': 'Bearer ' + 'o' * 40}

def fixture():
    at = now()
    kickoff = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    with connect() as c:
        mid = ingest_match(c, 'the-odds-api', 'event-1', 'E0', 'Arsenal', 'Chelsea', kickoff, True, 'scheduled', {})
        model = c.execute('INSERT INTO models(competition,created_at,cutoff,samples,payload,metrics) VALUES(?,?,?,?,?,?)', ('E0', at, at, 200, '{}', '{}')).lastrowid
        pred = {'selections':[{'market':'1x2','selection':'home','line':None,'player':'','probability':.6,'push':0}], 'sample_min':30}
        c.execute('INSERT INTO predictions(match_id,model_id,created_at,kickoff,payload,features) VALUES(?,?,?,?,?,?)', (mid, model, at, kickoff, dump(pred), '{}'))
        for selection, price in [('home',2),('draw',3),('away',4)]:
            add_quote(c,mid,'1x2',selection,None,'','Bet365',price,at,at,'the-odds-api','https://example.com',True)
    return mid

def test_auth_and_no_manual_routes(client):
    assert client.get('/api/v1/summary').status_code == 401
    assert client.get('/api/v1/summary', headers={'Authorization':'Bearer '+'c'*40}).status_code == 401
    assert client.post('/internal/tick', headers=OWNER).status_code == 404
    assert client.post('/api/bets',headers=OWNER,json={'quote_id':1}).status_code == 404
    result = client.get('/api/v1/summary',headers=OWNER)
    assert result.status_code == 200
    assert result.json()['mode']=='paper'
    assert result.json()['account']['balance']==1000
    assert result.headers['cache-control']=='no-store'
    assert 'owner_token' not in result.text and 'cron_secret' not in result.text

def test_missing_auth_configuration_fails_closed(client, monkeypatch):
    monkeypatch.delenv('MOBILE_OWNER_TOKEN')
    assert client.get('/api/v1/summary',headers=OWNER).status_code==503

def test_settings_conflicts_and_validation(client):
    strategy=client.get('/api/v1/engine',headers=OWNER).json()['strategy']
    changed={**strategy,'enabled':False}
    assert client.put('/api/v1/strategy',headers=OWNER,json=changed).json()['version']==2
    assert client.put('/api/v1/strategy',headers=OWNER,json=changed).status_code==409
    assert client.put('/api/v1/strategy',headers=OWNER,json={**changed,'version':2,'window_end':61}).status_code==422
    cfg=client.get('/api/v1/engine',headers=OWNER).json()['data_settings']
    assert client.put('/api/v1/data-settings',headers=OWNER,json={**cfg,'daily_credit_limit':500}).json()['version']==2
    assert client.put('/api/v1/data-settings',headers=OWNER,json=cfg).status_code==409

def test_duplicate_and_concurrent_entries(client):
    fixture()
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sum(pool.map(lambda _: select_automatic(), range(3)))==1
    result=client.get('/api/v1/bets',headers=OWNER).json()
    assert len(result['items'])==1
    assert result['items'][0]['stake']==20
    assert client.get('/api/v1/bets/1',headers=OWNER).json()['probability']==.6
    assert client.get('/api/v1/bets?state=settled',headers=OWNER).json()['items']==[]
    assert client.get('/api/v1/bets?limit=1001',headers=OWNER).status_code==422

def test_pause_and_stale_quotes(client):
    fixture()
    with connect() as c:
        cfg=setting(c,'strategy');cfg['enabled']=False;set_setting(c,'strategy',cfg)
    assert select_automatic()==0
    with connect() as c:
        cfg['enabled']=True;set_setting(c,'strategy',cfg)
        c.execute('UPDATE quotes SET quoted_at=?',((datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat(),))
    assert select_automatic()==0
    assert any(r['reason']=='Stale quote' for r in client.get('/api/v1/engine',headers=OWNER).json()['reasons'])

def test_leases_and_recovery(client):
    token=acquire('tick')
    assert token and acquire('tick') is None
    release('tick','wrong')
    assert acquire('tick') is None
    release('tick',token)
    assert acquire('tick')
    assert tick()['skipped']

def test_expired_job_retry(client):
    with connect() as c:
        c.execute("INSERT INTO mobile_jobs(id,kind,payload,priority,status,available_at,lease_until) VALUES('a','train','{}',1,'running',?,?)", (now(), '2000-01-01T00:00:00+00:00'))
    job=claim(now())
    assert job['id']=='a'
    complete(job,error=ValueError('Awaiting history'))
    with connect() as c:
        assert c.execute("SELECT status FROM mobile_jobs WHERE id='a'").fetchone()['status']=='queued'

def test_cadence_health(client):
    with connect() as c:
        set_setting(c,'mobile_last_success',(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat())
    assert client.get('/api/v1/engine',headers=OWNER).json()['status']=='running'
    with connect() as c:
        set_setting(c,'mobile_last_success',(datetime.now(timezone.utc)-timedelta(minutes=16)).isoformat())
    assert client.get('/api/v1/engine',headers=OWNER).json()['status']=='overdue'

def test_schedule_is_idempotent_and_isolated(client, monkeypatch):
    monkeypatch.setenv('MOBILE_ODDS_API_KEY','test')
    schedule(now());schedule(now())
    with connect() as c:
        jobs=list(c.execute('SELECT * FROM mobile_jobs'))
        assert len([j for j in jobs if j['kind']=='odds'])==5
        assert len([j for j in jobs if j['id'].startswith('archive:')])==20
        assert not any('CL:' in j['id'] for j in jobs)

def test_daily_budget_and_retry_charges(client, monkeypatch):
    monkeypatch.setenv('MOBILE_ODDS_API_KEY','never-log-this')
    with connect() as c:set_setting(c,'odds_api_config',{'version':1,'daily_credit_limit':4,'quota_reserve':10})
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(503,headers={'x-requests-last':'2','x-requests-remaining':'100'})
    provider=MobileOdds(httpx.Client(transport=httpx.MockTransport(handler)))
    for _ in range(3):
        with pytest.raises(OddsApiError) as error:provider.request('/sports/soccer_epl/odds',{})
        assert 'never-log-this' not in str(error.value)
    assert len(calls)==2
    with connect() as c:assert setting(c,'odds_api_daily')['credits']==4

def test_network_failure_keeps_credit_reservation(client, monkeypatch):
    monkeypatch.setenv('MOBILE_ODDS_API_KEY','test')
    def handler(request):raise httpx.ConnectError('secret URL',request=request)
    provider=MobileOdds(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(OddsApiError):provider.request('/sports/soccer_epl/scores',{})
    with connect() as c:assert setting(c,'odds_api_daily')['credits']==2

def test_quota_reserve(client, monkeypatch):
    monkeypatch.setenv('MOBILE_ODDS_API_KEY','test')
    with connect() as c:set_setting(c,'odds_api_quota',{'remaining':11})
    provider=MobileOdds(httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail('Must not call provider'))))
    with pytest.raises(OddsApiError,match='reserve'):provider.request('/sports/soccer_epl/odds',{})

def test_results_settle_once_and_preserve_snapshot(client):
    mid=fixture();select_automatic()
    with connect() as c:
        before=c.execute('SELECT snapshot FROM bets').fetchone()['snapshot']
        c.execute('UPDATE matches SET kickoff=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),mid))
        event={'id':'event-1','completed':True,'home_team':'Arsenal','away_team':'Chelsea','scores':[{'name':'Arsenal','score':'2'},{'name':'Chelsea','score':'1'}]}
        assert ingest_scores(c,[event],'E0',now())==1
    assert settle()==1 and settle()==0
    with connect() as c:
        assert portfolios(c)[0]['balance']==1020
        assert c.execute('SELECT snapshot FROM bets').fetchone()['snapshot']==before

def test_unverified_result_retains_stake(client):
    fixture();select_automatic()
    with connect() as c:
        assert ingest_scores(c,[{'id':'event-1','completed':True,'scores':[]}],'E0',now())==0
    assert settle()==0
    with connect() as c:assert portfolios(c)[0]['reserved']==20

def test_hosted_configuration_requires_database(monkeypatch):
    monkeypatch.setenv('RAILWAY_ENVIRONMENT_ID','test')
    monkeypatch.delenv('DATABASE_URL',raising=False)
    with pytest.raises(RuntimeError,match='DATABASE_URL'):configure()


def test_outside_window_does_not_repeat_expensive_price_scan(client, monkeypatch):
    mid=fixture()
    future=(datetime.now(timezone.utc)+timedelta(hours=3)).isoformat()
    with connect() as c:
        c.execute('UPDATE matches SET kickoff=? WHERE id=?',(future,mid))
        c.execute('UPDATE predictions SET kickoff=? WHERE match_id=?',(future,mid))
    monkeypatch.setattr('backend.mobile.engine.place_bet',lambda *args: pytest.fail('Entry helper must not run outside the window'))
    assert select_automatic()==0

def test_never_started_engine_becomes_overdue(client):
    with connect() as c:
        set_setting(c,'mobile_initialized',(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())
    assert client.get('/api/v1/engine',headers=OWNER).json()['status']=='overdue'

def test_retrying_jobs_degrade_engine_health(client):
    with connect() as c:
        set_setting(c,'mobile_last_success',now())
        set_setting(c,'mobile_last_run',{'jobs':1,'errors':1})
    assert client.get('/api/v1/engine',headers=OWNER).json()['status']=='degraded'

def test_database_outage_is_503_and_startup_recovers(monkeypatch):
    import psycopg
    import backend.mobile.api as api
    clock=[100.0]
    calls=[]
    real_initialize=api.initialize
    def initialize_once_unavailable():
        calls.append(True)
        if len(calls)==1:
            raise psycopg.OperationalError('private database connection details')
        real_initialize()
    monkeypatch.setattr(api,'initialize',initialize_once_unavailable)
    monkeypatch.setattr(api.time,'monotonic',lambda: clock[0])
    with TestClient(create_app(setup=False)) as client:
        response=client.get('/health')
        assert response.status_code==503
        assert 'private' not in response.text
        assert response.headers['retry-after']=='60'
        assert len(calls)==1
        clock[0]+=61
        assert client.get('/health').status_code==200
        assert len(calls)==2

def test_free_quota_check_recovers_after_provider_allowance_resets(client, monkeypatch):
    monkeypatch.setenv('MOBILE_ODDS_API_KEY','test')
    with connect() as c:
        set_setting(c,'odds_api_quota',{'remaining':0,'last_cost':2})
        set_setting(c,'odds_api_daily',{'date':now()[:10],'credits':100})
    calls=[]
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200,json=[],headers={'x-requests-remaining':'500'})
    provider=MobileOdds(httpx.Client(transport=httpx.MockTransport(handler)))
    provider.quota()
    assert calls==['/v4/sports']
    with connect() as c:
        assert setting(c,'odds_api_quota')['remaining']==500
        assert setting(c,'odds_api_daily')['credits']==100
    # Daily spending remains blocked until its own reset.
    with pytest.raises(OddsApiError,match='Daily'):
        provider.request('/sports/soccer_epl/odds',{})
    assert len(calls)==1

def test_quota_check_is_scheduled_once_per_discovery_cycle(client, monkeypatch):
    monkeypatch.setenv('MOBILE_ODDS_API_KEY','test')
    schedule(now());schedule(now())
    with connect() as c:
        assert c.execute("SELECT COUNT(*) FROM mobile_jobs WHERE kind='quota'").fetchone()[0]==1
    assert claim(now())['kind']=='quota'
