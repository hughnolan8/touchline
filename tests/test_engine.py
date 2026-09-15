from backend.mobile.engine import select_automatic as auto_bet
import json
from datetime import datetime,timedelta,timezone
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.db import connect,rows,now,dump,setting,set_setting
from backend.providers import ingest_match,add_quote,football_csv
from backend.models import fit_dc,score_grid,outcome,predict,evaluate
from backend.engine import opportunities,place_bet,settle,portfolios,devig,expected_return,fair_odds,history,generate_predictions

def shift(minutes):return (datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat()

def seed(quote_age=1,confirmed=True,verified=True,market='1x2',selection='home',line=None,push=0,prob=.6,minutes=30):
    at=now();kick=shift(minutes)
    with connect() as c:
        cfg=setting(c,'strategy');cfg['stake_mode']='flat';set_setting(c,'strategy',cfg)
        mid=ingest_match(c,'test','one','E0','Arsenal','Chelsea',kick,confirmed,'scheduled',{})
        model_id=c.execute('INSERT INTO models(competition,created_at,cutoff,samples,payload,metrics) VALUES(?,?,?,?,?,?)',('E0',at,at,200,'{}','{}')).lastrowid
        prediction={'selections':[dict(market=market,selection=selection,line=line,player='',probability=prob,push=push)],'sample_min':30,'outcomes':[.6,.2,.2]}
        c.execute('INSERT INTO predictions(match_id,model_id,created_at,kickoff,payload,features) VALUES(?,?,?,?,?,?)',(mid,model_id,at,kick,dump(prediction),'{}'))
        add_quote(c,mid,market,selection,line,'','Bet365',2.,shift(-quote_age),at,'test','https://example.org',verified)
        qid=c.execute('SELECT MAX(id) FROM quotes').fetchone()[0]
        sides=['home','draw','away'] if market=='1x2' else ['yes','no'] if market=='btts' else ['over','under']
        for side in sides:
            if side!=selection:add_quote(c,mid,market,side,line,'','Bet365',3.,shift(-quote_age),at,'test','https://example.org',verified)
    return mid,qid

def result(mid,status='finished',**stats):
    with connect() as c:c.execute('UPDATE matches SET status=?,stats=?,kickoff=? WHERE id=?',(status,dump(stats),shift(-120),mid))

def test_probability_and_push_math():
    grid=score_grid(1.6,1.1,-.06)
    assert grid.min()>=0 and grid.sum()==pytest.approx(1)
    assert sum(outcome(grid))==pytest.approx(1)
    assert expected_return(.5,2)==0
    assert expected_return(.5,2,.1)==pytest.approx(.1)
    assert fair_odds(.5,.1)==pytest.approx(1.8)

def test_margin_removal_complete_same_line_and_time():
    q=[dict(market='1x2',selection=s,odds=p,quoted_at=now()) for s,p in [('home',2),('draw',3.5),('away',4)]]
    assert sum(devig(q).values())==pytest.approx(1)
    assert devig(q[:2])=={}
    q[0]['quoted_at']=shift(-3);assert devig(q)=={}

@pytest.mark.parametrize('age,confirmed,verified',[(16,True,True),(1,False,True),(1,True,False),(-2,True,True)])
def test_unsafe_quotes_excluded(age,confirmed,verified):
    seed(age,confirmed,verified)
    with connect() as c:assert opportunities(c)==[]

def test_automatic_immutable_reservation_and_duplicate():
    mid,qid=seed()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');bid=place_bet(c,qid)
        assert portfolios(c)[0]['available']==990
        before=c.execute('SELECT snapshot FROM bets').fetchone()[0]
        with pytest.raises(ValueError):place_bet(c,qid)
        c.execute("UPDATE predictions SET payload='{}'")
        assert c.execute('SELECT snapshot FROM bets').fetchone()[0]==before
    result(mid,hg=2,ag=1);assert settle()==1;assert settle()==0
    with connect() as c:
        account=portfolios(c)[0];assert account['profit']==10;assert account['reserved']==0;assert account['balance']==1010

@pytest.mark.parametrize('status,hg,ag,market,selection,line,expected,profit',[
 ('finished',0,1,'1x2','home',None,'lost',-10),('finished',1,1,'goals','over',2,'push',0),('cancelled',None,None,'1x2','home',None,'void',0),('finished',1,1,'btts','yes',None,'won',10),('finished',1,0,'corners','over',9.5,'review',None)])
def test_settlement_cases(status,hg,ag,market,selection,line,expected,profit):
    mid,qid=seed(market=market,selection=selection,line=line)
    with connect() as c:c.execute('BEGIN IMMEDIATE');place_bet(c,qid)
    result(mid,status,hg=hg,ag=ag);settle()
    with connect() as c:
        b=dict(c.execute('SELECT * FROM bets').fetchone());assert b['status']==expected;assert b['profit']==profit

def test_postponement_does_not_settle():
    mid,qid=seed()
    with connect() as c:c.execute('BEGIN IMMEDIATE');place_bet(c,qid)
    result(mid,'postponed');assert settle()==0
    with connect() as c:assert portfolios(c)[0]['reserved']==10

def test_auto_limits_and_restart_idempotence():
    mid,qid=seed();assert auto_bet()==1;assert auto_bet()==0
    with connect() as c:
        assert portfolios(c)[0]['reserved']==10
        config=setting(c,'strategy');config['max_exposure']=.005;set_setting(c,'strategy',config)
        c.execute('DELETE FROM bets')
    assert auto_bet()==0

@pytest.mark.parametrize('minutes',[5,70,-5])
def test_no_retrospective_or_outside_window(minutes):
    seed(minutes=minutes);assert auto_bet()==0

def test_line_matching_does_not_borrow_other_prediction():
    mid,qid=seed(market='goals',selection='over',line=2.5)
    with connect() as c:
        c.execute('UPDATE quotes SET line=3.5');assert opportunities(c)==[]

def test_same_file_and_identity_are_idempotent_and_missing_is_null():
    body='Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,HC,AC\nE0,01/01/2025,15:00,Arsenal,Chelsea,2,1,,4\n'
    with connect() as c:
        assert football_csv(c,body,'test',now())==1;football_csv(c,body,'test',now())
        assert c.execute('SELECT COUNT(*) FROM matches').fetchone()[0]==1
        assert json.loads(c.execute('SELECT stats FROM matches').fetchone()[0])['hc'] is None
        with pytest.raises(ValueError):football_csv(c,'broken,headers\n1,2','test',now())

def test_batch_download_is_not_a_fresh_quote():
    dt=datetime.now()+timedelta(days=2)
    body=f'Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A\nE0,{dt:%d/%m/%Y},15:00,Arsenal,Chelsea,2,3,4\n'
    with connect() as c:
        football_csv(c,body,'test',now());quote=dict(c.execute('SELECT * FROM quotes LIMIT 1').fetchone())
        assert quote['quoted_at'] is None and quote['verified']==0

def test_training_filters_future_and_late_observations():
    with connect() as c:
        ingest_match(c,'test','old','E0','Arsenal','Chelsea',shift(-10000),True,'finished',dict(hg=2,ag=0),shift(-5000))
        ingest_match(c,'test','future','E0','Arsenal','Chelsea',shift(10000),True,'finished',dict(hg=9,ag=0),now())
        assert len(history(c,'E0',now()))==1
        assert len(history(c,'E0',shift(-6000)))==0



def test_conflicting_source_result_quarantined():
    with connect() as c:
        ingest_match(c,'a','1','E0','Arsenal','Chelsea',shift(-200),True,'finished',dict(hg=2,ag=1))
        assert ingest_match(c,'b','2','E0','Arsenal FC','Chelsea FC',shift(-200),True,'finished',dict(hg=0,ag=1)) is None
        assert c.execute('SELECT COUNT(*) FROM quarantine').fetchone()[0]==1



def test_full_training_prediction_bet_result_flow():
    rng=np.random.default_rng(42);records=[];cutoff=now()
    for i in range(180):
        home,away=('Arsenal','Chelsea') if i%2 else ('Chelsea','Arsenal')
        records.append(dict(id=str(i),home=home,away=away,kickoff=shift(-1000*(181-i)),stats=dict(hg=int(rng.poisson(1.6)),ag=int(rng.poisson(1.1)))))
    model={'dc':fit_dc(records,cutoff),'selected':'baseline'}
    predicted=predict(model,records,'Arsenal','Chelsea');assert predicted and sum(predicted['outcomes'])==pytest.approx(1)
    mid,qid=seed()
    with connect() as c:
        c.execute('UPDATE predictions SET payload=?',(dump(predicted),));c.execute('BEGIN IMMEDIATE') if not c.in_transaction else None
        c.execute('UPDATE quotes SET odds=3 WHERE id=?',(qid,))
        assert opportunities(c);place_bet(c,qid)
    result(mid,hg=1,ag=0);assert settle()==1
    with connect() as c:assert portfolios(c)[0]['balance']==1020

def test_refresh_preserves_point_in_time_training_history():
    first=shift(-100);cutoff=shift(-50)
    with connect() as c:
        mid=ingest_match(c,'a','one','E0','Arsenal','Chelsea',shift(-10000),True,'finished',dict(hg=2,ag=0),first)
        ingest_match(c,'a','one','E0','Arsenal','Chelsea',shift(-10000),True,'finished',dict(hg=3,ag=0),now())
        old=history(c,'E0',cutoff)
        assert len(old)==1 and old[0]['stats']['hg']==2
        assert history(c,'E0',now())[0]['stats']['hg']==3

def test_incomplete_market_is_not_ranked():
    mid,qid=seed()
    with connect() as c:
        c.execute("DELETE FROM quotes WHERE selection='draw'")
        assert opportunities(c)==[]
        assert 'Incomplete or asynchronous bookmaker market' in opportunities(c,include_indicative=True)[0]['reasons']

def test_source_alias_retained_for_rescheduling_existing_fixture():
    with connect() as c:
        original=ingest_match(c,'a','a1','E0','Arsenal','Chelsea',shift(3000),True,'scheduled',{})
        imported=ingest_match(c,'csv','stable','E0','Arsenal','Chelsea',shift(3000),True,'scheduled',{})
        assert original==imported
        later=ingest_match(c,'csv','stable','E0','Arsenal','Chelsea',shift(20000),True,'scheduled',{})
        assert later==original
        assert c.execute('SELECT COUNT(*) FROM matches').fetchone()[0]==1

def test_reverted_state_has_a_new_observation():
    with connect() as c:
        kickoff=shift(-10000)
        ingest_match(c,'a','1','E0','Arsenal','Chelsea',kickoff,True,'finished',dict(hg=2,ag=0),shift(-100))
        ingest_match(c,'a','1','E0','Arsenal','Chelsea',kickoff,True,'finished',dict(hg=3,ag=0),shift(-50))
        ingest_match(c,'a','1','E0','Arsenal','Chelsea',kickoff,True,'finished',dict(hg=2,ag=0),now())
        assert history(c,'E0',now())[0]['stats']['hg']==2

def test_new_unverified_quote_does_not_resurrect_old_verified_price():
    mid,qid=seed()
    with connect() as c:
        add_quote(c,mid,'1x2','home',None,'','Bet365',2.1,None,now(),'test','https://example.org',False)
        assert opportunities(c)==[]

def test_concurrent_schema_migration_is_serialised():
    from concurrent.futures import ThreadPoolExecutor
    from backend.db import init
    with connect() as c:
        c.execute('DROP TABLE observations')
        c.execute('CREATE TABLE observations(id INTEGER PRIMARY KEY,match_id TEXT,observed_at TEXT,payload TEXT,UNIQUE(match_id,payload))')
        c.execute('INSERT INTO observations VALUES(1,?,?,?)',('old',now(),'{}'))
    # Legacy fixture has no match FK; make its canonical fixture before migrating.
    with connect() as c:
        c.execute('INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?,?)',('old','E0','a','b',now(),1,'scheduled','{}','test','legacy',now()))
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:init(),range(4)))
    with connect() as c:
        assert c.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==1
        assert 'observed_at,payload' in c.execute("SELECT sql FROM sqlite_master WHERE name='observations'").fetchone()[0]

def test_unchanged_prediction_skips_history_and_model_download(monkeypatch):
    mid,_=seed()
    with connect() as c:
        c.execute('UPDATE predictions SET created_at=?',(now(),))
    monkeypatch.setattr('backend.engine.history',lambda *a: pytest.fail('Unchanged fixtures must not download training history'))
    assert generate_predictions()==0

def test_prediction_refreshes_after_reschedule_or_next_day(monkeypatch):
    mid,_=seed(minutes=3000)
    prediction={'selections':[], 'sample_min':30}
    calls=[]
    monkeypatch.setattr('backend.engine.history',lambda *a: calls.append('history') or [])
    monkeypatch.setattr('backend.engine.predict',lambda *a: prediction)
    with connect() as c:c.execute('UPDATE matches SET kickoff=? WHERE id=?',(shift(3100),mid))
    assert generate_predictions()==1
    assert generate_predictions()==0
    # Daily refresh creates a new immutable row even for the same model and fixture.
    assert generate_predictions(at=shift(1500))==1
    with connect() as c:
        assert c.execute('SELECT COUNT(*) FROM predictions WHERE match_id=?',(mid,)).fetchone()[0]==3
    assert generate_predictions(at=shift(3200))==0
    assert calls==['history','history']
