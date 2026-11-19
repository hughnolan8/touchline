-- Single schema, applied by touchline/db.py. Bump SCHEMA_VERSION there when changing it.

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL                -- JSON
);

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,               -- norm(display name)
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_aliases (
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    team_id TEXT NOT NULL REFERENCES teams(id),
    PRIMARY KEY (source, name)
);

CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,               -- "<league>:<home>-<away>:<kickoff date>" at creation
    league TEXT NOT NULL,
    understat_id TEXT UNIQUE,          -- NULL for fixtures known only from The Odds API
    home TEXT NOT NULL REFERENCES teams(id),
    away TEXT NOT NULL REFERENCES teams(id),
    kickoff TEXT NOT NULL,             -- ISO-8601 UTC
    status TEXT NOT NULL,              -- scheduled | finished
    hg INTEGER,
    ag INTEGER,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS matches_league_kickoff ON matches(league, kickoff);

CREATE TABLE IF NOT EXISTS player_match_stats (
    match_id TEXT NOT NULL REFERENCES matches(id),
    player_id TEXT NOT NULL,           -- Understat player id
    name TEXT NOT NULL,
    team_id TEXT NOT NULL,
    starter INTEGER NOT NULL,
    minutes REAL NOT NULL,
    xg REAL NOT NULL,
    xa REAL NOT NULL,
    PRIMARY KEY (match_id, player_id)
);
CREATE INDEX IF NOT EXISTS pms_team ON player_match_stats(team_id);

CREATE TABLE IF NOT EXISTS lineups (
    match_id TEXT PRIMARY KEY REFERENCES matches(id),
    captured_at TEXT NOT NULL,         -- must be before kickoff
    source TEXT NOT NULL,
    payload TEXT NOT NULL              -- JSON {"home": [names], "away": [names]}
);

CREATE TABLE IF NOT EXISTS odds_quotes (
    match_id TEXT NOT NULL REFERENCES matches(id),
    bookmaker TEXT NOT NULL,
    selection TEXT NOT NULL,
    odds REAL NOT NULL,
    quoted_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (match_id, bookmaker, selection, quoted_at)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    match_id TEXT NOT NULL REFERENCES matches(id),
    kind TEXT NOT NULL,                -- entry | close
    captured_at TEXT NOT NULL,
    payload TEXT NOT NULL,             -- JSON {selection: Price}
    PRIMARY KEY (match_id, kind)
);

CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY,
    league TEXT NOT NULL,
    version TEXT NOT NULL,             -- baseline-v1 | xi-v2
    created_at TEXT NOT NULL,
    samples INTEGER NOT NULL,
    payload TEXT NOT NULL              -- JSON fitted parameters
);
CREATE INDEX IF NOT EXISTS models_league_version ON models(league, version, id);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY,
    match_id TEXT NOT NULL REFERENCES matches(id),
    model_id INTEGER NOT NULL REFERENCES models(id),
    version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    with_lineup INTEGER NOT NULL DEFAULT 0,
    home REAL NOT NULL,
    draw REAL NOT NULL,
    away REAL NOT NULL,
    home_goals REAL NOT NULL,
    away_goals REAL NOT NULL,
    UNIQUE (match_id, model_id, with_lineup)
);

CREATE TABLE IF NOT EXISTS decisions (
    match_id TEXT PRIMARY KEY REFERENCES matches(id),
    created_at TEXT NOT NULL,
    action TEXT NOT NULL,              -- bet | no_bet | missed
    reason TEXT NOT NULL,
    payload TEXT NOT NULL,             -- JSON
    notified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY,
    match_id TEXT NOT NULL UNIQUE REFERENCES matches(id),   -- one paper bet per fixture
    prediction_id INTEGER REFERENCES predictions(id),
    created_at TEXT NOT NULL,
    selection TEXT NOT NULL,
    odds REAL NOT NULL,
    bookmaker TEXT NOT NULL,
    stake REAL NOT NULL,
    edge REAL NOT NULL,
    probability REAL NOT NULL,
    model_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- open | won | lost | void
    profit REAL,
    settled_at TEXT,
    close_odds REAL,
    close_bookmaker TEXT,
    clv REAL
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY,
    job TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    summary TEXT
);
CREATE INDEX IF NOT EXISTS job_runs_job ON job_runs(job, id);

CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload TEXT NOT NULL
);
