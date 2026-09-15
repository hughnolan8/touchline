"""Persistence and job coordination for the iOS backend."""
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from backend.db import connect, init, now, setting, set_setting

LEAGUES = ('E0', 'SP1', 'D1', 'I1', 'F1')
DATA_DEFAULTS = dict(version=1, auto_refresh=True, interval_minutes=15,
                     daily_credit_limit=100, quota_reserve=10)


def configure():
    # Railway injects the private PostgreSQL reference as DATABASE_URL.
    # Hosted services must never silently fall back to an ephemeral SQLite file.
    if os.environ.get('RAILWAY_ENVIRONMENT_ID') and not os.environ.get('DATABASE_URL'):
        raise RuntimeError('DATABASE_URL is required on Railway')
    if not os.environ.get('DATABASE_URL'):
        os.environ['ENGINE_DB'] = os.environ.get('MOBILE_ENGINE_DB', 'data/mobile/engine.sqlite3')
    os.environ['MOBILE_PROCESS'] = '1'


def initialize():
    init()
    with connect() as c:
        if os.environ.get('DATABASE_URL'):
            c.execute('SELECT pg_advisory_xact_lock(814729302)')
        c.execute('''CREATE TABLE IF NOT EXISTS mobile_leases(
          name TEXT PRIMARY KEY, token TEXT NOT NULL, expires_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS mobile_jobs(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
          priority INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
          attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL,
          lease_until TEXT, finished_at TEXT, message TEXT)''')
        c.execute('CREATE INDEX IF NOT EXISTS mobile_jobs_due ON mobile_jobs(status,available_at,priority)')
        if setting(c, 'mobile_initialized') is None:
            # Refuse accidentally reusing any database with existing activity.
            if c.execute('SELECT 1 FROM bets LIMIT 1').fetchone():
                raise RuntimeError('Mobile database must start with an empty ledger')
            set_setting(c, 'odds_api_config', DATA_DEFAULTS)
            set_setting(c, 'mobile_initialized', now())


@contextmanager
def transaction():
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if os.environ.get('DATABASE_URL'):
            c.execute('SELECT pg_advisory_xact_lock(814729301)')
        yield c


def acquire(name, seconds=280):
    token = secrets.token_hex(16)
    at = now()
    until = (datetime.fromisoformat(at) + timedelta(seconds=seconds)).isoformat()
    with transaction() as c:
        c.execute('INSERT OR IGNORE INTO mobile_leases VALUES(?,?,?)', (name, '', at))
        claimed = c.execute('UPDATE mobile_leases SET token=?,expires_at=? WHERE name=? AND expires_at<=? RETURNING name',
                            (token, until, name, at)).fetchone()
    return token if claimed else None


def release(name, token):
    with connect() as c:
        c.execute('DELETE FROM mobile_leases WHERE name=? AND token=?', (name, token))
