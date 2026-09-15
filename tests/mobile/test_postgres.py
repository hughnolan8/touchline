"""Opt-in integration tests, strictly restricted to the dedicated mobile test database."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
import pytest
from backend.db import init, connect, now, rows, set_setting
from backend.mobile.store import initialize, transaction, acquire, release

@pytest.fixture
def postgres(monkeypatch):
    if os.environ.get('RUN_MOBILE_POSTGRES_TESTS') != '1':
        pytest.skip('Dedicated Postgres integration run not requested')
    url=os.environ['TEST_DATABASE_URL']
    if not urlsplit(url).path.startswith('/tl_mobile_test_'):
        pytest.fail('Refusing to test against a non-test database')
    monkeypatch.setenv('DATABASE_URL',url)
    monkeypatch.setenv('MOBILE_PROCESS','1')
    initialize()
    with connect() as c:
        for table in ['bets','predictions','quotes','match_aliases','observations','matches','aliases','teams','models']:
            c.execute('DELETE FROM '+table)
        c.execute('DELETE FROM mobile_leases')
        c.execute('DELETE FROM mobile_jobs')
    yield

def test_postgres_lease_is_exclusive(postgres):
    with ThreadPoolExecutor(max_workers=3) as pool:
        values=list(pool.map(lambda _: acquire('integration'),range(3)))
    assert sum(bool(v) for v in values)==1
    release('integration',next(v for v in values if v))
    assert acquire('integration')

def test_postgres_ignored_insert_and_next_statement(postgres):
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO mobile_jobs(id,kind,payload,priority,available_at) VALUES('unique','odds','{}',1,?)",(now(),))
        c.execute("INSERT OR IGNORE INTO mobile_jobs(id,kind,payload,priority,available_at) VALUES('unique','odds','{}',1,?)",(now(),))
        assert c.execute('SELECT COUNT(*) FROM mobile_jobs').fetchone()[0]==1

def test_postgres_transaction_lock_serializes_updates(postgres):
    from backend.db import setting
    with connect() as c:set_setting(c,'integration_counter',0)
    def increment(_):
        with transaction() as c:
            value=setting(c,'integration_counter');set_setting(c,'integration_counter',value+1)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(increment,range(8)))
    with connect() as c:assert setting(c,'integration_counter')==8

def test_postgres_ledger_concurrency_and_settlement(postgres):
    from test_mobile import fixture
    from backend.mobile.engine import select_automatic
    from backend.engine import settle, portfolios
    from datetime import datetime, timedelta, timezone
    from backend.db import dump
    mid=fixture()
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sum(pool.map(lambda _: select_automatic(),range(3)))==1
    with connect() as c:
        c.execute("UPDATE matches SET status='finished',stats=?,kickoff=? WHERE id=?",(dump({'hg':2,'ag':1}),(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),mid))
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: settle(),range(2)))==1
    with connect() as c:
        assert portfolios(c)[0]['balance']==1020

def test_postgres_scheduler_runs_without_network(postgres, monkeypatch):
    from backend.mobile.engine import schedule, claim
    monkeypatch.setenv('MOBILE_ODDS_API_KEY','test')
    schedule(now())
    schedule(now())
    job=claim(now())
    assert job and job['kind']=='quota'
    with connect() as c:
        assert c.execute("SELECT COUNT(*) FROM mobile_jobs WHERE kind='odds'").fetchone()[0]==5
