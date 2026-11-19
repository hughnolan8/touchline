"""Leakage-safe player feature storage and confirmed-XI aggregation."""
import hashlib
import json
import math
from datetime import datetime

from .db import dump, now, quarantine, rows
from .providers import canonical, norm

SOURCE = 'understat'
HALF_LIFE_DAYS = 180
PRIOR_MINUTES = 540

def _number(value):
    try: return float(value or 0)
    except (TypeError, ValueError): return 0.0

def _player_id(source, source_id, name):
    return hashlib.sha256(f'{source}|{source_id or norm(name)}'.encode()).hexdigest()[:24]

def resolve_player(c, source, source_id, name, team_id, create=True):
    """Resolve only provider IDs or an existing exact normalized team alias."""
    source_id = str(source_id or '')
    if source_id:
        row = c.execute('SELECT player_id FROM player_aliases WHERE source=? AND source_id=?', (source, source_id)).fetchone()
        if row: return row[0]
    candidates = [row for row in rows(c, 'SELECT DISTINCT pa.player_id,p.name FROM player_aliases pa JOIN players p ON p.id=pa.player_id WHERE pa.team_id=?', (team_id,)) if norm(row['name']) == norm(name)]
    if len(candidates) == 1:
        player_id = candidates[0]['player_id']
    elif candidates:
        return None
    elif create:
        player_id = _player_id(source, source_id, name)
        c.execute('INSERT OR IGNORE INTO players VALUES(?,?)', (player_id, name))
    else:
        return None
    if source_id:
        c.execute('INSERT OR IGNORE INTO player_aliases VALUES(?,?,?,?,?)', (source, source_id, name, team_id, player_id))
    return player_id

def save_roster(c, match_id, sides):
    """Store Understat's already-completed roster; malformed rows are quarantined."""
    match = c.execute('SELECT home,away FROM matches WHERE id=?', (match_id,)).fetchone()
    if not match: return 0
    inserted = 0
    for side_key, team_id in (('h', match['home']), ('a', match['away'])):
        roster = sides.get(side_key, [])
        if isinstance(roster, dict): roster = roster.values()
        for value in roster:
            try:
                item = value
                if isinstance(value, dict) and isinstance(value.get('player'), dict):
                    item = {**value, **value['player']}
                name = item.get('player_name') or item.get('player') or item.get('name')
                source_id = item.get('player_id') or item.get('id')
                if not name: raise ValueError('Roster player has no name')
                player_id = resolve_player(c, SOURCE, source_id, name, team_id)
                if not player_id: raise ValueError('Ambiguous player identity')
                minutes = _number(item.get('time') or item.get('minutes'))
                # Understat versions expose either an explicit starter flag or
                # a substitution-in reference.  An outgoing substitution does
                # not make a player a substitute, so never use `substitute`
                # alone to exclude a starter.
                stated = item.get('starter', item.get('isStarter'))
                starter = int(bool(stated) if stated is not None else minutes > 0 and not item.get('substituted_in') and not item.get('in'))
                c.execute('INSERT OR IGNORE INTO player_match_stats VALUES(?,?,?,?,?,?,?,?)', (match_id, player_id, team_id, starter, minutes, _number(item.get('xG')), _number(item.get('xA')), str(item.get('position') or '')))
                inserted += 1
            except (AttributeError, TypeError, ValueError) as error:
                quarantine(c, SOURCE, str(error), {'match_id': match_id, 'row': value})
    return inserted

def save_lineup_snapshot(c, match_id, source, source_fixture_id, lineups, captured_at=None):
    """Persist a known XI with the time it became available.

    A snapshot is deliberately separate from completed-match player statistics:
    the former is an input that may be used for a pre-kickoff prediction, while
    the latter is only an outcome observation.  This timestamp is what keeps a
    replay from accidentally using a lineup learned after the fixture started.
    """
    captured_at = captured_at or now()
    match = c.execute('SELECT kickoff FROM matches WHERE id=?', (match_id,)).fetchone()
    if not match or datetime.fromisoformat(captured_at) > datetime.fromisoformat(match['kickoff']):
        return False
    if not isinstance(lineups, dict) or set(lineups) != {'home', 'away'}:
        return False
    if any(not isinstance(lineups[side], list) or len(lineups[side]) != 11 for side in lineups):
        return False
    c.execute('INSERT OR IGNORE INTO lineup_snapshots(match_id,source,source_fixture_id,captured_at,payload) VALUES(?,?,?,?,?)',
              (match_id, source, str(source_fixture_id), captured_at, dump(lineups)))
    return True

def latest_lineup_snapshot(c, match_id, at):
    """Return the last complete XI that was known no later than ``at``."""
    row = c.execute('SELECT captured_at,payload FROM lineup_snapshots WHERE match_id=? AND captured_at<=? ORDER BY captured_at DESC,id DESC LIMIT 1', (match_id, at)).fetchone()
    if not row:
        return None
    try:
        lineups = json.loads(row['payload'])
    except (TypeError, ValueError):
        return None
    if not isinstance(lineups, dict) or set(lineups) != {'home', 'away'} or any(not isinstance(lineups[side], list) or len(lineups[side]) != 11 for side in lineups):
        return None
    return {'captured_at': row['captured_at'], 'lineups': lineups}

def lineup_features(c, match_id, side, lineup, cutoff, league='E0'):
    """Return XI xG/xA totals using only appearances before ``cutoff``."""
    match = c.execute('SELECT home,away FROM matches WHERE id=?', (match_id,)).fetchone()
    team_id = match['home'] if side == 'home' else match['away']
    if not isinstance(lineup, list) or len(lineup) != 11: return None
    baseline_row = c.execute("SELECT COALESCE(SUM(xg)/NULLIF(SUM(minutes),0)*90,0),COALESCE(SUM(xa)/NULLIF(SUM(minutes),0)*90,0) FROM player_match_stats p JOIN matches m ON m.id=p.match_id WHERE m.competition=? AND m.kickoff<?", (league, cutoff)).fetchone()
    baseline = (_number(baseline_row[0]), _number(baseline_row[1]))
    starters = []
    for player in lineup:
        player_id = player.get('internal_id') or resolve_player(c, player.get('source', ''), player.get('id'), player.get('name', ''), team_id, create=False)
        if not player_id: return None
        records = rows(c, "SELECT p.*,m.kickoff FROM player_match_stats p JOIN matches m ON m.id=p.match_id WHERE p.player_id=? AND m.competition=? AND m.kickoff<?", (player_id, league, cutoff))
        weighted_minutes = weighted_xg = weighted_xa = 0.0
        for record in records:
            age = max(0, (datetime.fromisoformat(cutoff) - datetime.fromisoformat(record['kickoff'])).total_seconds() / 86400)
            weight = math.exp(-math.log(2) * age / HALF_LIFE_DAYS)
            weighted_minutes += weight * record['minutes']; weighted_xg += weight * record['xg']; weighted_xa += weight * record['xa']
        strength = weighted_minutes / (weighted_minutes + PRIOR_MINUTES)
        xg90 = strength * (weighted_xg / weighted_minutes * 90 if weighted_minutes else 0) + (1-strength) * baseline[0]
        xa90 = strength * (weighted_xa / weighted_minutes * 90 if weighted_minutes else 0) + (1-strength) * baseline[1]
        starters.append({'id': player_id, 'name': player.get('name'), 'xg90': xg90, 'xa90': xa90, 'contribution': xg90 + xa90})
    context = team_context(c, team_id, cutoff, league)
    return {'xg90': sum(x['xg90'] for x in starters), 'xa90': sum(x['xa90'] for x in starters), 'starters': sorted(starters, key=lambda x: x['contribution'], reverse=True)[:3], **context}

def team_context(c, team_id, cutoff, league):
    """Pre-kickoff team context; never reads a match at or after ``cutoff``."""
    games = rows(c, "SELECT home,away,kickoff,stats FROM matches WHERE competition=? AND status='finished' AND kickoff<? AND (home=? OR away=?) ORDER BY kickoff DESC LIMIT 5", (league, cutoff, team_id, team_id))
    cutoff_dt = datetime.fromisoformat(cutoff)
    if not games:
        return {'rest_days': 7.0, 'congestion': 0.0, 'attack_form': 0.0, 'defence_form': 0.0}
    scored = conceded = 0.0
    for game in games:
        score = json.loads(game['stats'])
        home_goals, away_goals = _number(score.get('hg')), _number(score.get('ag'))
        mine, theirs = (home_goals, away_goals) if game['home'] == team_id else (away_goals, home_goals)
        scored += mine; conceded += theirs
    latest = datetime.fromisoformat(games[0]['kickoff'])
    rest = max(0.0, min(21.0, (cutoff_dt - latest).total_seconds() / 86400))
    recent = sum((cutoff_dt - datetime.fromisoformat(g['kickoff'])).total_seconds() <= 14 * 86400 for g in games)
    return {'rest_days': rest, 'congestion': float(recent), 'attack_form': scored / len(games), 'defence_form': conceded / len(games)}

def historical_lineups(c, match_id, cutoff, league='E0'):
    match = c.execute('SELECT home,away FROM matches WHERE id=?', (match_id,)).fetchone()
    result = {}
    for side, team_id in (('home', match['home']), ('away', match['away'])):
        starters = [dict(row, internal_id=row['id']) for row in rows(c, 'SELECT p.id,p.name FROM player_match_stats s JOIN players p ON p.id=s.player_id WHERE s.match_id=? AND s.team_id=? AND s.starter=1', (match_id, team_id))]
        if len(starters) != 11: return None
        result[side] = lineup_features(c, match_id, side, starters, cutoff, league)
        if not result[side]: return None
    return result
