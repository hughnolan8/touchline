from datetime import datetime,timedelta,timezone
import json
from backend.db import connect,now,dump
from backend.engine import devig,account,matches,place_required_bet,settle
from backend.engine import forecast,train
from backend.providers import ingest_match,add_quote

def stamp(minutes):return (datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat()
def fixture():
 with connect() as c:
  mid=ingest_match(c,'test','one','E0','Arsenal','Chelsea',stamp(58),True,'scheduled',{})
  for side,odds in [('home',2.4),('draw',3.4),('away',3.2)]:add_quote(c,mid,'1x2',side,None,'','Bet365',odds,now(),now(),'test','https://example.test',True)
  m=dict(c.execute("SELECT m.*,h.name home_name,a.name away_name FROM matches m JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away WHERE m.id=?",(mid,)).fetchone())
 return mid,m
def test_devig_sums_to_one():assert sum(devig([{'selection':'home','odds':2},{'selection':'draw','odds':3},{'selection':'away','odds':4}]).values())==1
def test_mandatory_negative_edge_uses_one_pound_fallback():
 mid,m=fixture()
 with connect() as c:
  at=(datetime.fromisoformat(m['kickoff'])-timedelta(minutes=1)).isoformat()
  assert place_required_bet(c,m,{'probabilities':{'home':.2,'draw':.2,'away':.2}},at)=='placed'
  assert c.execute('SELECT stake FROM bets').fetchone()[0]==1
def test_future_fixture_keeps_prediction_but_cannot_create_bet():
 with connect() as c:
  mid=ingest_match(c,'test','tomorrow','E0','Arsenal','Chelsea',stamp(24*60),True,'scheduled',{})
  for side,odds in [('home',2.4),('draw',3.4),('away',3.2)]:add_quote(c,mid,'1x2',side,None,'','Bet365',odds,now(),now(),'test','https://example.test',True)
  m=dict(c.execute("SELECT m.*,h.name home_name,a.name away_name FROM matches m JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away WHERE m.id=?",(mid,)).fetchone())
  assert place_required_bet(c,m,{'probabilities':{'home':.6,'draw':.2,'away':.2}})=='blocked: fixture is not being played today'
  assert c.execute('SELECT COUNT(*) FROM bets WHERE match_id=?',(mid,)).fetchone()[0]==0
def test_settlement_is_idempotent():
 mid,m=fixture()
 with connect() as c:
  at=(datetime.fromisoformat(m['kickoff'])-timedelta(minutes=1)).isoformat()
  place_required_bet(c,m,{'probabilities':{'home':.6,'draw':.2,'away':.2}},at);c.execute('UPDATE matches SET status=?,stats=? WHERE id=?',('finished',dump({'hg':2,'ag':1}),mid))
 assert settle()==1 and settle()==0
 with connect() as c:assert account(c)['balance']>1000
def test_forecast_uses_canonical_team_ids():
 mid,m=fixture()
 with connect() as c:
  for i in range(40):
   c.execute('INSERT INTO matches(id,competition,home,away,kickoff,time_confirmed,status,stats,source,source_id,observed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(f'h{i}','E0',m['home'],m['away'],stamp(-1000-i),1,'finished',dump({'hg':1+i%3,'ag':i%2}),'test',f'h{i}',now()))
  train(c)
  assert forecast(c,m) is not None

def test_matches_only_returns_the_next_seven_days():
 at='2026-09-17T12:00:00+00:00'
 with connect() as c:
  near=ingest_match(c,'test','near','E0','Arsenal','Chelsea','2026-09-24T12:00:00+00:00',True,'scheduled',{})
  ingest_match(c,'test','later','E0','Liverpool','Everton','2026-09-24T12:01:00+00:00',True,'scheduled',{})
  assert [m['id'] for m in matches(c,at=at)]==[near]
