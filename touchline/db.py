"""SQLite access: connect, schema, settings, quarantine and job-run logging."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from touchline.config import config

SCHEMA_VERSION = 1
SCHEMA = Path(__file__).with_name("schema.sql")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def utc(value: str) -> str:
    """Normalise any offset-aware ISO timestamp to the canonical UTC string form."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def minutes_until(kickoff: str, at: str) -> float:
    return (datetime.fromisoformat(kickoff) - datetime.fromisoformat(at)).total_seconds() / 60


def dump(value) -> str:
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


def init(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return
    conn.executescript(SCHEMA.read_text())
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """One short-lived connection per unit of work; commits on success."""
    path = config().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        init(conn)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(conn: sqlite3.Connection, sql: str, args=()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, args)]


def get_setting(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, dump(value)),
    )


def quarantine(conn: sqlite3.Connection, source: str, reason: str, payload) -> None:
    conn.execute(
        "INSERT INTO quarantine(created_at, source, reason, payload) VALUES(?, ?, ?, ?)",
        (now(), source, reason, json.dumps(payload, default=str)[:4000]),
    )


@contextmanager
def job_run(name: str) -> Iterator[dict]:
    """Log a job's start, outcome and summary dict to job_runs (one row per run)."""
    with connect() as conn:
        run_id = conn.execute(
            "INSERT INTO job_runs(job, started_at) VALUES(?, ?)", (name, now())
        ).lastrowid
    summary: dict = {}
    ok = False
    try:
        yield summary
        ok = True
    except Exception as error:
        summary["error"] = f"{type(error).__name__}: {error}"[:500]
        raise
    finally:
        with connect() as conn:
            conn.execute(
                "UPDATE job_runs SET finished_at=?, ok=?, summary=? WHERE id=?",
                (now(), int(ok), dump(summary), run_id),
            )
