"""Persistence and job coordination for the Touchline web backend."""
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from backend.db import connect, init, now, setting, set_setting
from backend.competitions import BY_CODE

LEAGUES = tuple(BY_CODE)
DATA_DEFAULTS = dict(version=1)


def configure():
    # Railway injects the private PostgreSQL reference as DATABASE_URL.
    # Hosted services must never silently fall back to an ephemeral SQLite file.
    if os.environ.get('RAILWAY_ENVIRONMENT_ID') and not os.environ.get('DATABASE_URL'):
        raise RuntimeError('DATABASE_URL is required on Railway')
    if not os.environ.get('DATABASE_URL'):
        os.environ['ENGINE_DB'] = os.environ.get('TOUCHLINE_DB_PATH') or os.environ.get('MOBILE_ENGINE_DB', 'data/runtime/engine.sqlite3')
    os.environ['TOUCHLINE_PROCESS'] = '1'


def _table_exists(connection, name):
    if os.environ.get('DATABASE_URL'):
        return connection.execute('SELECT to_regclass(?)', (name,)).fetchone()[0] is not None
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _rename_legacy_state(connection):
    for legacy, current in (('mobile_leases', 'app_leases'), ('mobile_jobs', 'app_jobs')):
        if _table_exists(connection, legacy) and not _table_exists(connection, current):
            connection.execute(f'ALTER TABLE {legacy} RENAME TO {current}')
    connection.execute('DROP INDEX IF EXISTS mobile_jobs_due')


def initialize():
    init()
    with connect() as c:
        if os.environ.get('DATABASE_URL'):
            c.execute('SELECT pg_advisory_xact_lock(814729302)')
        _rename_legacy_state(c)
        c.execute('''CREATE TABLE IF NOT EXISTS app_leases(
          name TEXT PRIMARY KEY, token TEXT NOT NULL, expires_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS app_jobs(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
          priority INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
          attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL,
          lease_until TEXT, finished_at TEXT, message TEXT)''')
        c.execute('CREATE INDEX IF NOT EXISTS app_jobs_due ON app_jobs(status,available_at,priority)')
        if setting(c, 'app_initialized') is None:
            legacy_initialized = setting(c, 'mobile_initialized')
            if legacy_initialized is not None:
                set_setting(c, 'app_initialized', legacy_initialized)
                c.execute("DELETE FROM settings WHERE key='mobile_initialized'")
        if setting(c, 'app_initialized') is None:
            # Refuse accidentally reusing any database with existing activity.
            if c.execute('SELECT 1 FROM bets LIMIT 1').fetchone():
                raise RuntimeError('Touchline database must start with an empty ledger')
            set_setting(c, 'app_initialized', now())


@contextmanager
def transaction():
    with connect() as c:
        if os.environ.get('DATABASE_URL'):
            # psycopg opens the transaction on the first statement.  Sending
            # BEGIN here can therefore produce "already a transaction in
            # progress" in PostgreSQL.
            c.execute('SELECT pg_advisory_xact_lock(814729301)')
        else:
            c.execute('BEGIN IMMEDIATE')
        yield c


def acquire(name, seconds=280):
    token = secrets.token_hex(16)
    at = now()
    until = (datetime.fromisoformat(at) + timedelta(seconds=seconds)).isoformat()
    with transaction() as c:
        c.execute('INSERT OR IGNORE INTO app_leases VALUES(?,?,?)', (name, '', at))
        claimed = c.execute('UPDATE app_leases SET token=?,expires_at=? WHERE name=? AND expires_at<=? RETURNING name',
                            (token, until, name, at)).fetchone()
    return token if claimed else None


def release(name, token):
    with connect() as c:
        c.execute('DELETE FROM app_leases WHERE name=? AND token=?', (name, token))
