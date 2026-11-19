"""Pull data into SQLite: football-data fixtures/results, Understat rosters, FotMob XIs."""

import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from touchline.db import connect, dump, quarantine, rows, set_setting, utc
from touchline.sources import football_data, fotmob, understat
from touchline.teams import canonical
from touchline.types import Fixture

log = logging.getLogger(__name__)
SOURCE = "football-data"


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


def insert_match(conn, league: str, home: str, away: str, kickoff: str, at: str) -> str:
    match_id = f"{league}:{home}-{away}:{kickoff[:10]}"
    conn.execute(
        "INSERT OR IGNORE INTO matches(id, league, home, away, kickoff, status, updated_at) "
        "VALUES(?,?,?,?,?,'scheduled',?)",
        (match_id, league, home, away, kickoff, at),
    )
    return match_id


def store_fixture(conn: sqlite3.Connection, f: Fixture, at: str) -> str | None:
    """Upsert one football-data fixture/result, adopting a scheduled fixture within 48 h."""
    if f.finished and f.kickoff > at:
        quarantine(conn, SOURCE, "result before kickoff", f.__dict__)
        return None
    home, away = canonical(conn, SOURCE, f.home), canonical(conn, SOURCE, f.away)
    if home == away:
        quarantine(conn, SOURCE, "home and away identical", f.__dict__)
        return None
    match_id = find_match(conn, f.league, home, away, f.kickoff) or insert_match(
        conn, f.league, home, away, f.kickoff, at
    )
    conn.execute(
        "UPDATE matches SET kickoff=?, status=?, hg=?, ag=?, updated_at=? WHERE id=?",
        (f.kickoff, "finished" if f.finished else "scheduled", f.hg, f.ag, at, match_id),
    )
    return match_id


def _store(fixtures: list[Fixture], rejected: list[dict], at: str) -> int:
    with connect() as conn:
        for raw in rejected:
            quarantine(conn, SOURCE, "unparseable row", raw)
        return sum(bool(store_fixture(conn, f, at)) for f in fixtures)


def sync_results(league: str, seasons, at: str, fetch=football_data.fetch_results) -> int:
    """Import season results; fixtures still unplayed 3 days after kick-off become postponed."""
    count = sum(_store(*fetch(league, season), at) for season in seasons)
    stale = (datetime.fromisoformat(at) - timedelta(days=3)).isoformat()
    with connect() as conn:
        conn.execute(
            "UPDATE matches SET status='postponed', updated_at=? WHERE league=? AND "
            "status='scheduled' AND kickoff<?",
            (at, league, stale),
        )
        set_setting(conn, f"synced:{league}", at)
    return count


def sync_fixtures(at: str, fetch=football_data.fetch_fixtures) -> int:
    """Next week's fixtures for every league (one request)."""
    fixtures, rejected = fetch()
    count = _store([f for f in fixtures if not f.finished and f.kickoff > at], rejected, at)
    with connect() as conn:
        set_setting(conn, "synced:fixtures", at)
    return count


def hydrate_rosters(limit: int, fetch=understat.fetch_roster) -> int:
    """Fetch player stats for finished matches that have none yet (newest first)."""
    with connect() as conn:
        pending = rows(
            conn,
            "SELECT id, understat_id, home, away FROM matches m WHERE status='finished' "
            "AND understat_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM player_match_stats p "
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
