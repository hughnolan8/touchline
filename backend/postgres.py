"""Small compatibility layer for the SQLite-compatible repository SQL on PostgreSQL."""
import os
import re
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def _sql(statement):
    statement = statement.strip()
    statement = statement.replace("BEGIN IMMEDIATE", "BEGIN")
    statement = statement.replace(" line IS ?", " line IS NOT DISTINCT FROM ?")
    statement = statement.replace("INSERT OR IGNORE INTO", "INSERT INTO")
    if statement.startswith("INSERT INTO") and "ON CONFLICT" not in statement and "INSERT OR IGNORE" in statement:
        statement += " ON CONFLICT DO NOTHING"
    statement = statement.replace("?", "%s")
    # SQLite's julianday() has no Postgres equivalent.  The application uses
    # this only to identify the same fixture within two days; compare the
    # timestamp distance in seconds when running against PostgreSQL instead.
    statement = statement.replace(
        "abs(julianday(kickoff)-julianday(%s))<2",
        "abs(EXTRACT(EPOCH FROM (kickoff::timestamptz - %s::timestamptz)))<172800",
    )
    return statement


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = None

    def execute(self, statement, params=()):
        original = statement
        statement = _sql(statement)
        if "INSERT OR IGNORE" in original and "ON CONFLICT" not in statement:
            statement += " ON CONFLICT DO NOTHING"
        wants_id = statement.startswith("INSERT INTO") and any(f"INSERT INTO {table}" in statement for table in ("models", "jobs", "bets"))
        if wants_id and "RETURNING" not in statement:
            statement += " RETURNING id"
        self.cursor.execute(statement, params)
        if wants_id:
            row = self.cursor.fetchone()
            self.lastrowid = row["id"] if row else None
        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        return Row(row) if row else None

    def __iter__(self):
        for row in self.cursor:
            yield Row(row)


class Connection:
    def __init__(self, connection):
        self.connection = connection
        self.in_transaction = False

    def execute(self, statement, params=()):
        if statement.strip().upper().startswith("BEGIN"):
            self.in_transaction = True
        cursor = Cursor(self.connection.cursor(row_factory=dict_row)).execute(statement, params)
        return cursor

    def commit(self):
        self.connection.commit()
        self.in_transaction = False

    def rollback(self):
        self.connection.rollback()
        self.in_transaction = False


@contextmanager
def connect():
    raw = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=10, prepare_threshold=None)
    connection = Connection(raw)
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        raw.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS aliases(source TEXT,name TEXT,team_id TEXT REFERENCES teams(id),PRIMARY KEY(source,name));
CREATE TABLE IF NOT EXISTS matches(id TEXT PRIMARY KEY,competition TEXT NOT NULL,home TEXT NOT NULL,away TEXT NOT NULL,kickoff TEXT NOT NULL,time_confirmed INTEGER NOT NULL,status TEXT NOT NULL,stats TEXT NOT NULL,source TEXT NOT NULL,source_id TEXT NOT NULL,observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS match_aliases(source TEXT,source_id TEXT,match_id TEXT REFERENCES matches(id),PRIMARY KEY(source,source_id));
CREATE TABLE IF NOT EXISTS snapshots(id BIGSERIAL PRIMARY KEY,source TEXT,url TEXT,observed_at TEXT,content_hash TEXT,body TEXT,UNIQUE(source,url,content_hash));
CREATE TABLE IF NOT EXISTS observations(id BIGSERIAL PRIMARY KEY,match_id TEXT REFERENCES matches(id),observed_at TEXT,payload TEXT NOT NULL,UNIQUE(match_id,observed_at,payload));
CREATE TABLE IF NOT EXISTS quotes(id BIGSERIAL PRIMARY KEY,match_id TEXT REFERENCES matches(id),market TEXT,selection TEXT,line DOUBLE PRECISION,player TEXT NOT NULL DEFAULT '',rules TEXT NOT NULL,bookmaker TEXT,odds DOUBLE PRECISION,quoted_at TEXT,collected_at TEXT,source TEXT,url TEXT,verified INTEGER NOT NULL DEFAULT 0,fingerprint TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS models(id BIGSERIAL PRIMARY KEY,competition TEXT,created_at TEXT,cutoff TEXT,samples INTEGER,payload TEXT,metrics TEXT);
CREATE TABLE IF NOT EXISTS predictions(id BIGSERIAL PRIMARY KEY,match_id TEXT REFERENCES matches(id),model_id BIGINT REFERENCES models(id),created_at TEXT,kickoff TEXT,payload TEXT,features TEXT,UNIQUE(match_id,model_id,kickoff,features));
CREATE TABLE IF NOT EXISTS bets(id BIGSERIAL PRIMARY KEY,portfolio TEXT CHECK(portfolio IN ('automatic','manual')),match_id TEXT REFERENCES matches(id),quote_id BIGINT REFERENCES quotes(id),prediction_id BIGINT REFERENCES predictions(id),created_at TEXT,stake DOUBLE PRECISION,snapshot TEXT,status TEXT DEFAULT 'open',profit DOUBLE PRECISION,settled_at TEXT,reason TEXT,UNIQUE(portfolio,quote_id));
CREATE UNIQUE INDEX IF NOT EXISTS one_auto_fixture ON bets(match_id) WHERE portfolio='automatic';
CREATE TABLE IF NOT EXISTS jobs(id BIGSERIAL PRIMARY KEY,kind TEXT,status TEXT DEFAULT 'queued',created_at TEXT,finished_at TEXT,message TEXT);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,status TEXT,checked_at TEXT,records INTEGER,message TEXT);
CREATE TABLE IF NOT EXISTS quarantine(id BIGSERIAL PRIMARY KEY,source TEXT,reason TEXT,payload TEXT,created_at TEXT,UNIQUE(source,reason,payload));
CREATE INDEX IF NOT EXISTS matches_kickoff ON matches(kickoff);
CREATE INDEX IF NOT EXISTS quotes_match ON quotes(match_id,id);
CREATE INDEX IF NOT EXISTS predictions_match ON predictions(match_id,id);
"""


def init():
    with connect() as connection:
        # API and both workers can start simultaneously during a deployment.
        connection.execute('SELECT pg_advisory_xact_lock(814729302)')
        for statement in SCHEMA.split(";"):
            if statement.strip():
                connection.execute(statement)
