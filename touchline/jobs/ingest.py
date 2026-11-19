"""Pull data from sources into SQLite: fixtures/results, rosters, odds and confirmed XIs."""

import logging
import sqlite3
from datetime import UTC, datetime

from touchline.db import connect, dump, quarantine, rows, set_setting, utc
from touchline.sources import fotmob, understat
from touchline.teams import canonical
from touchline.types import Fixture

log = logging.getLogger(__name__)


def find_match(conn, league: str, home: str, away: str, kickoff: str) -> str | None:
    """The unique scheduled fixture between these teams within 48 h of `kickoff`."""
    candidates = rows(
        conn,
        "SELECT id, kickoff FROM matches WHERE league=? AND home=? AND "
        "away=? AND status='scheduled'",
        (league, home, away),
    )
    target = datetime.fromisoformat(kickoff)
    near = [
        c["id"]
        for c in candidates
        if abs((datetime.fromisoformat(c["kickoff"]) - target).total_seconds()) < 172800
    ]
    return near[0] if len(near) == 1 else None


def insert_match(
    conn, league: str, home: str, away: str, kickoff: str, at: str, understat_id: str | None = None
) -> str:
    match_id = f"{league}:{home}-{away}:{kickoff[:10]}"
    conn.execute(
        "INSERT INTO matches(id, league, understat_id, home, away, kickoff, status, "
        "updated_at) VALUES(?,?,?,?,?,?,'scheduled',?)",
        (match_id, league, understat_id, home, away, kickoff, at),
    )
    return match_id


def store_fixture(conn: sqlite3.Connection, f: Fixture, at: str) -> str | None:
    """Upsert one Understat fixture/result, adopting an Odds-API-only fixture if one exists."""
    if f.finished and f.kickoff > at:
        quarantine(conn, "understat", "result before kickoff", f.__dict__)
        return None
    home, away = canonical(conn, "understat", f.home), canonical(conn, "understat", f.away)
    if home == away:
        quarantine(conn, "understat", "home and away identical", f.__dict__)
        return None
    row = conn.execute("SELECT id FROM matches WHERE understat_id=?", (f.source_id,)).fetchone()
    match_id = row[0] if row else find_match(conn, f.league, home, away, f.kickoff)
    if not match_id:
        match_id = insert_match(conn, f.league, home, away, f.kickoff, at, f.source_id)
    conn.execute(
        "UPDATE matches SET understat_id=?, kickoff=?, status=?, hg=?, ag=?, updated_at=? "
        "WHERE id=?",
        (
            f.source_id,
            f.kickoff,
            "finished" if f.finished else "scheduled",
            f.hg,
            f.ag,
            at,
            match_id,
        ),
    )
    return match_id


def sync_league(league: str, seasons, at: str, fetch=understat.fetch_season) -> int:
    count = 0
    for season in seasons:
        payload = fetch(league, season)
        with connect() as conn:
            for raw in payload:
                try:
                    if store_fixture(conn, understat.parse_match(raw, league), at):
                        count += 1
                except (KeyError, TypeError, ValueError) as error:
                    quarantine(conn, "understat", str(error), raw)
            set_setting(conn, f"synced:{league}", at)
    return count


def hydrate_rosters(limit: int, fetch=understat.fetch_roster) -> int:
    """Fetch player stats for finished matches that have none yet (newest first)."""
    with connect() as conn:
        pending = rows(
            conn,
            "SELECT id, home, away FROM matches m WHERE status='finished' "
            "AND NOT EXISTS (SELECT 1 FROM player_match_stats p "
            "WHERE p.match_id=m.id) ORDER BY kickoff DESC LIMIT ?",
            (limit,),
        )
    done = 0
    for match in pending:
        try:
            stats = understat.parse_roster(fetch(match["understat_id"]))
        except Exception as error:  # provider outages must never block the tick
            with connect() as conn:
                quarantine(conn, "understat", f"roster failed: {error}", {"match": match["id"]})
            continue
        with connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO player_match_stats VALUES(?,?,?,?,?,?,?,?)",
                [
                    (
                        match["id"],
                        s.player_id,
                        s.name,
                        match[s.side],
                        int(s.starter),
                        s.minutes,
                        s.xg,
                        s.xa,
                    )
                    for s in stats
                ],
            )
        done += 1
    return done


def capture_lineup(match: dict, at: str, client_factory=fotmob.FotMob) -> bool:
    """Save a confirmed FotMob XI for one scheduled match, if FotMob has published it."""
    day = datetime.fromisoformat(match["kickoff"]).astimezone(UTC).strftime("%Y%m%d")
    with client_factory() as client:
        candidates = client.day(day)
        with connect() as conn:
            found = None
            for c in candidates:
                try:
                    home = canonical(conn, "fotmob", c["home"]["name"])
                    away = canonical(conn, "fotmob", c["away"]["name"])
                except (KeyError, TypeError, ValueError):
                    continue
                if (home, away) == (match["home"], match["away"]):
                    found = c["id"]
                    break
        lineup = client.lineup(found) if found is not None else None
    if not lineup or at >= match["kickoff"]:
        return False
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO lineups(match_id, captured_at, source, payload) VALUES(?,?,?,?)",
            (match["id"], utc(at), "fotmob", dump({"home": lineup.home, "away": lineup.away})),
        )
    return True
