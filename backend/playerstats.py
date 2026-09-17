"""Leakage-safe player feature storage and confirmed-XI aggregation."""
import hashlib
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

def lineup_features(c, match_id, side, lineup, cutoff):
    """Return XI xG/xA totals using only appearances before ``cutoff``."""
    match = c.execute('SELECT home,away FROM matches WHERE id=?', (match_id,)).fetchone()
    team_id = match['home'] if side == 'home' else match['away']
    if not isinstance(lineup, list) or len(lineup) != 11: return None
    league = c.execute("SELECT COALESCE(SUM(xg)/NULLIF(SUM(minutes),0)*90,0),COALESCE(SUM(xa)/NULLIF(SUM(minutes),0)*90,0) FROM player_match_stats p JOIN matches m ON m.id=p.match_id WHERE m.kickoff<?", (cutoff,)).fetchone()
    baseline = (_number(league[0]), _number(league[1]))
    starters = []
    for player in lineup:
        player_id = player.get('internal_id') or resolve_player(c, 'api-football', player.get('id'), player.get('name', ''), team_id, create=False)
        if not player_id: return None
        records = rows(c, "SELECT p.*,m.kickoff FROM player_match_stats p JOIN matches m ON m.id=p.match_id WHERE p.player_id=? AND m.kickoff<?", (player_id, cutoff))
        weighted_minutes = weighted_xg = weighted_xa = 0.0
        for record in records:
            age = max(0, (datetime.fromisoformat(cutoff) - datetime.fromisoformat(record['kickoff'])).total_seconds() / 86400)
            weight = math.exp(-math.log(2) * age / HALF_LIFE_DAYS)
            weighted_minutes += weight * record['minutes']; weighted_xg += weight * record['xg']; weighted_xa += weight * record['xa']
        strength = weighted_minutes / (weighted_minutes + PRIOR_MINUTES)
        xg90 = strength * (weighted_xg / weighted_minutes * 90 if weighted_minutes else 0) + (1-strength) * baseline[0]
        xa90 = strength * (weighted_xa / weighted_minutes * 90 if weighted_minutes else 0) + (1-strength) * baseline[1]
        starters.append({'id': player_id, 'name': player.get('name'), 'xg90': xg90, 'xa90': xa90, 'contribution': xg90 + xa90})
    return {'xg90': sum(x['xg90'] for x in starters), 'xa90': sum(x['xa90'] for x in starters), 'starters': sorted(starters, key=lambda x: x['contribution'], reverse=True)[:3]}

def historical_lineups(c, match_id, cutoff):
    match = c.execute('SELECT home,away FROM matches WHERE id=?', (match_id,)).fetchone()
    result = {}
    for side, team_id in (('home', match['home']), ('away', match['away'])):
        starters = [dict(row, internal_id=row['id']) for row in rows(c, 'SELECT p.id,p.name FROM player_match_stats s JOIN players p ON p.id=s.player_id WHERE s.match_id=? AND s.team_id=? AND s.starter=1', (match_id, team_id))]
        if len(starters) != 11: return None
        result[side] = lineup_features(c, match_id, side, starters, cutoff)
        if not result[side]: return None
    return result
