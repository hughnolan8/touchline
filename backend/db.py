"""SQLite persistence. JSON snapshots are append-only; ledger updates only settle bets."""
import json
import fcntl
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from . import postgres

COMPETITIONS = {'E0': 'Premier League'}
DEFAULT_STRATEGY = dict(enabled=True, stake=10.0, min_edge=0.05, max_exposure=0.10, max_quote_age=15, window_start=60, window_end=15, version=1, stake_mode='kelly', kelly_fraction=0.25, max_bet_fraction=0.02, min_stake=1.0)

def now(): return datetime.now(timezone.utc).isoformat()
def stamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None: raise ValueError('Timestamp must include a timezone')
    return dt.astimezone(timezone.utc).isoformat()
def dump(value): return json.dumps(value, separators=(',', ':'), allow_nan=False)
def path(): return Path(os.environ.get('ENGINE_DB', 'data/mobile/engine.sqlite3'))

@contextmanager
def connect():
    if os.environ.get('DATABASE_URL'):
        with postgres.connect() as c:
            yield c
        return
    p = path(); p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback(); raise
    finally: c.close()

def rows(c, sql, args=()): return [dict(r) for r in c.execute(sql, args)]
def setting(c, key, default=None):
    r = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return json.loads(r[0]) if r else default

def set_setting(c, key, value):
    c.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, dump(value)))

def init():
    if os.environ.get('DATABASE_URL'):
        postgres.init()
        with connect() as c:
            existing=setting(c,'strategy')
            if existing is None:set_setting(c,'strategy',DEFAULT_STRATEGY)
            elif any(key not in existing for key in DEFAULT_STRATEGY):set_setting(c,'strategy',{**DEFAULT_STRATEGY,**existing,'version':existing['version']+1})
        return
    schema_lock=path().with_suffix('.schema.lock');schema_lock.parent.mkdir(parents=True,exist_ok=True)
    with schema_lock.open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        _init()

def _init():
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY,name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS aliases(source TEXT,name TEXT,team_id TEXT REFERENCES teams(id),PRIMARY KEY(source,name));
        CREATE TABLE IF NOT EXISTS matches(id TEXT PRIMARY KEY,competition TEXT NOT NULL,home TEXT NOT NULL,away TEXT NOT NULL,kickoff TEXT NOT NULL,time_confirmed INTEGER NOT NULL,status TEXT NOT NULL,stats TEXT NOT NULL,source TEXT NOT NULL,source_id TEXT NOT NULL,observed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS match_aliases(source TEXT,source_id TEXT,match_id TEXT REFERENCES matches(id),PRIMARY KEY(source,source_id));
        CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,source TEXT,url TEXT,observed_at TEXT,content_hash TEXT,body TEXT,UNIQUE(source,url,content_hash));
        CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,match_id TEXT REFERENCES matches(id),observed_at TEXT,payload TEXT NOT NULL,UNIQUE(match_id,observed_at,payload));
        CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY,match_id TEXT REFERENCES matches(id),market TEXT,selection TEXT,line REAL,player TEXT NOT NULL DEFAULT '',rules TEXT NOT NULL,bookmaker TEXT,odds REAL,quoted_at TEXT,collected_at TEXT,source TEXT,url TEXT,verified INTEGER NOT NULL DEFAULT 0,fingerprint TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS models(id INTEGER PRIMARY KEY,competition TEXT,created_at TEXT,cutoff TEXT,samples INTEGER,payload TEXT,metrics TEXT);
        CREATE TABLE IF NOT EXISTS predictions(id INTEGER PRIMARY KEY,match_id TEXT REFERENCES matches(id),model_id INTEGER REFERENCES models(id),created_at TEXT,kickoff TEXT,payload TEXT,features TEXT,UNIQUE(match_id,model_id,kickoff,features));
        CREATE TABLE IF NOT EXISTS bets(id INTEGER PRIMARY KEY,portfolio TEXT CHECK(portfolio IN ('automatic','manual')),match_id TEXT REFERENCES matches(id),quote_id INTEGER REFERENCES quotes(id),prediction_id INTEGER REFERENCES predictions(id),created_at TEXT,stake REAL,snapshot TEXT,status TEXT DEFAULT 'open',profit REAL,settled_at TEXT,reason TEXT,UNIQUE(portfolio,quote_id));
        CREATE UNIQUE INDEX IF NOT EXISTS one_auto_fixture ON bets(match_id) WHERE portfolio='automatic';
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,kind TEXT,status TEXT DEFAULT 'queued',created_at TEXT,finished_at TEXT,message TEXT);
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,status TEXT,checked_at TEXT,records INTEGER,message TEXT);
        CREATE TABLE IF NOT EXISTS quarantine(id INTEGER PRIMARY KEY,source TEXT,reason TEXT,payload TEXT,created_at TEXT,UNIQUE(source,reason,payload));
        CREATE INDEX IF NOT EXISTS matches_kickoff ON matches(kickoff);
        CREATE INDEX IF NOT EXISTS quotes_match ON quotes(match_id,id);
        CREATE INDEX IF NOT EXISTS predictions_match ON predictions(match_id,id);
        ''')
        old=c.execute("SELECT sql FROM sqlite_master WHERE name='observations'").fetchone()[0]
        if 'UNIQUE(match_id,payload)' in old:
            c.executescript('''CREATE TABLE IF NOT EXISTS observations_v2(id INTEGER PRIMARY KEY,match_id TEXT REFERENCES matches(id),observed_at TEXT,payload TEXT NOT NULL,UNIQUE(match_id,observed_at,payload));
            INSERT OR IGNORE INTO observations_v2 SELECT * FROM observations;
            DROP TABLE observations; ALTER TABLE observations_v2 RENAME TO observations;''')
        c.execute('INSERT OR IGNORE INTO match_aliases SELECT source,source_id,id FROM matches')
        existing=setting(c,'strategy')
        if existing is None:set_setting(c,'strategy',DEFAULT_STRATEGY)
        elif any(key not in existing for key in DEFAULT_STRATEGY):set_setting(c,'strategy',{**DEFAULT_STRATEGY,**existing,'version':existing['version']+1})

def quarantine(c, source, reason, payload):
    c.execute('INSERT OR IGNORE INTO quarantine(source,reason,payload,created_at) VALUES(?,?,?,?)', (source, reason, dump(payload), now()))
