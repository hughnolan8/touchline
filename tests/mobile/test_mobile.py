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
from backend.mobile.provider import MobileOdds
from backend.external_features import parse_understat, import_understat
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

def test_predictions_expose_upcoming_model_forecasts(client):
    fixture()
    response = client.get('/api/v1/predictions', headers=OWNER)
    assert response.status_code == 200
    forecast = response.json()[0]
    assert forecast['home'] == 'Arsenal'
    assert forecast['away'] == 'Chelsea'
    assert forecast['model_id'] > 0
    selection = forecast['selections'][0]
    assert {key: selection[key] for key in ('market', 'selection', 'line', 'probability', 'push', 'odds', 'bookmaker')} == {
        'market':'1x2', 'selection':'home', 'line':None, 'probability':.6, 'push':0, 'odds':2, 'bookmaker':'Bet365'}
    assert selection['implied_probability'] == pytest.approx(.5)
    assert selection['discrepancy'] == pytest.approx(.1)
    assert selection['quote_time']

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

def test_operations_expose_readiness_and_retry_visibility(client):
    with connect() as c:
        set_setting(c, 'mobile_last_success', now())
        set_setting(c, 'mobile_last_run', {'jobs': 0, 'errors': 0})
        c.execute("INSERT INTO mobile_jobs(id,kind,payload,priority,status,attempts,available_at,message) VALUES('retrying:file','file','{}',1,'queued',1,?, 'Source temporarily unavailable')", (now(),))
    operations = client.get('/api/v1/engine', headers=OWNER).json()['operations']
    assert operations['last_cycle_outcome'] == 'completed_no_work_due'
    assert operations['retrying_jobs'] == 1
    assert operations['status'] == 'warning'
    assert any(issue['code'] == 'jobs_retrying' for issue in operations['issues'])
    assert {league['competition'] for league in operations['leagues']} == {'E0', 'SP1', 'D1', 'I1', 'F1'}

def test_optional_research_failure_does_not_degrade_live_engine(client):
    with connect() as c:
        set_setting(c, 'mobile_last_success', now())
        c.execute("INSERT INTO mobile_jobs(id,kind,payload,priority,status,available_at) VALUES('understat:test','understat','{}',1,'failed',?)", (now(),))
    assert client.get('/api/v1/engine', headers=OWNER).json()['status'] == 'running'

def test_schedule_is_idempotent_and_isolated(client, monkeypatch):
    monkeypatch.setenv('MOBILE_ODDS_API_KEY','test')
    fixture()
    schedule(now());schedule(now())
    with connect() as c:
        jobs=list(c.execute('SELECT * FROM mobile_jobs'))
        assert len([j for j in jobs if j['kind']=='odds'])==1
        assert len([j for j in jobs if j['id'].startswith('archive:')])==20
        assert len([j for j in jobs if j['kind']=='understat'])==5
        bucket = int(datetime.fromisoformat(now()).timestamp()) // (15 * 60)
        assert {j['id'] for j in jobs if j['kind']=='odds'} == {f'odds:E0:window:{bucket}'}
        assert not any('CL:' in j['id'] for j in jobs)

def test_schedule_adds_targeted_result_collection_for_overdue_open_bet(client, monkeypatch):
    monkeypatch.setenv('MOBILE_ODDS_API_KEY', 'test')
    mid = fixture()
    assert select_automatic() == 1
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with connect() as c:
        c.execute('UPDATE matches SET kickoff=? WHERE id=?', (past, mid))
    schedule(now())
    bucket = int(datetime.fromisoformat(now()).timestamp()) // (15 * 60)
    with connect() as c:
        job = c.execute('SELECT * FROM mobile_jobs WHERE id=?', (f'result:E0:{bucket}',)).fetchone()
        assert job and job['kind'] == 'result' and job['priority'] == 0

def test_engine_jobs_include_their_last_run_timestamp(client):
    finished = now()
    with connect() as c:
        c.execute("INSERT INTO mobile_jobs(id,kind,payload,priority,status,available_at,finished_at) VALUES('timestamped','file','{}',1,'done',?,?)", (finished, finished))
    job = next(job for job in client.get('/api/v1/engine', headers=OWNER).json()['jobs'] if job['id'] == 'timestamped')
    assert job['finished_at'] == finished

def test_schedule_supersedes_legacy_understat_season_jobs(client):
    at = now()
    with connect() as c:
        c.execute("INSERT INTO mobile_jobs(id,kind,payload,priority,status,available_at,message) VALUES(?,?,?,?,?,?,?)",
                  ('understat:E0:2526:legacy', 'understat', '{\"competition\":\"E0\",\"season\":\"2526\"}', 28, 'failed', at, 'Invalid Understat season'))
    schedule(at)
    with connect() as c:
        legacy = c.execute("SELECT status, message FROM mobile_jobs WHERE id='understat:E0:2526:legacy'").fetchone()
        assert dict(legacy) == {'status': 'superseded', 'message': 'Superseded obsolete Understat season job'}
        assert c.execute("SELECT 1 FROM mobile_jobs WHERE id LIKE 'understat:E0:20%:%' AND status='queued'").fetchone()

def test_external_features_enrich_only_exact_fixtures(client):
    kickoff=(datetime.now(timezone.utc)-timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0).isoformat()
    with connect() as c:
        match_id=ingest_match(c, 'football-data', 'fixture-1', 'E0', 'Arsenal', 'Chelsea', kickoff, True, 'finished', {'hg':2, 'ag':1})
        payload={'datesData': {'dates': [{'id':'u-1', 'datetime':kickoff, 'h':{'title':'Arsenal'}, 'a':{'title':'Chelsea'}, 'xG':{'h':'1.87', 'a':'0.42'}}, {'id':'unknown', 'datetime':kickoff, 'h':{'title':'Unknown'}, 'a':{'title':'Chelsea'}, 'xG':{'h':'1', 'a':'1'}}]}}
        assert import_understat(c, 'E0', payload, now()) == 1
        stats=json.loads(c.execute('SELECT stats FROM matches WHERE id=?', (match_id,)).fetchone()['stats'])
        assert stats['hxg'] == pytest.approx(1.87)
        assert stats['axg'] == pytest.approx(.42)
        assert c.execute("SELECT COUNT(*) FROM quarantine WHERE source='understat'").fetchone()[0] == 1

def test_external_feature_parsers_accept_documented_shapes(client):
    assert parse_understat([{'id':'1','datetime':'2026-09-10 20:00:00','h':{'title':'Arsenal'},'a':{'title':'Chelsea'},'xG':{'h':'1.2','a':'0.8'}}]) == [{'date':'2026-09-10','home':'Arsenal','away':'Chelsea','hxg':1.2,'axg':.8,'source_id':'1'}]
    assert parse_understat({'dates':[{'id':'2','datetime':'2026-09-10 20:00:00','h':{'title':'Arsenal'},'a':{'title':'Chelsea'},'xG':{'h':'1.2','a':'0.8'}}]}) == [{'date':'2026-09-10','home':'Arsenal','away':'Chelsea','hxg':1.2,'axg':.8,'source_id':'2'}]
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
    with pytest.raises(OddsApiError):provider.request('/sports/soccer_epl/odds',{})
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
        assert ingest_match(c, 'football-data', 'E0:result', 'E0', 'Arsenal', 'Chelsea',
                            (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(), True,
                            'finished', {'hg':2, 'ag':1}, now()) == mid
    assert settle()==1 and settle()==0
    with connect() as c:
        assert portfolios(c)[0]['balance']==1020
        assert c.execute('SELECT snapshot FROM bets').fetchone()['snapshot']==before

def test_unverified_result_retains_stake(client):
    fixture();select_automatic()
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
