"""Fixture and result imports from Understat via understatapi."""
from datetime import datetime, timedelta, timezone

from understatapi import UnderstatClient

from .db import now, quarantine
from .competitions import competition
from .providers import ingest_match
from .playerstats import save_roster


SOURCE = 'understat'
REQUEST_TIMEOUT = 30


def season_start(at=None):
    """Return the start year of the Premier League season containing ``at``."""
    value = datetime.fromisoformat(at or now())
    return value.year if value.month >= 7 else value.year - 1


def _kickoff(value):
    """Understat league fixture datetimes are offset-free UTC values."""
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).isoformat()


def _match_fields(match):
    finished = bool(match.get('isResult'))
    stats = {}
    if finished:
        goals = match['goals']
        stats = {'hg': int(goals['h']), 'ag': int(goals['a'])}
    return (
        str(match['id']), match['h']['title'], match['a']['title'], _kickoff(match['datetime']),
        finished, 'finished' if finished else 'scheduled', stats,
    )


def sync_seasons(connection, league, seasons, client_factory=UnderstatClient, observed=None):
    """Import one supported league's Understat fixtures for season start-years.

    The league endpoint supplies both upcoming fixtures and completed results.
    Only completed records carry final scores; no xG, forecasts, or odds are
    imported into Touchline.
    """
    competition_info = competition(league)
    imported = 0
    observed = observed or now()
    fixture_cutoff = (datetime.fromisoformat(observed) + timedelta(days=7)).isoformat()
    with client_factory() as client:
        endpoint = client.league(league=competition_info.understat)
        for season in seasons:
            for match in endpoint.get_match_data(season=str(season), timeout=REQUEST_TIMEOUT):
                try:
                    source_id, home, away, kickoff, confirmed, status, stats = _match_fields(match)
                    if status == 'finished' and kickoff > observed:
                        raise ValueError('Result appears before kickoff')
                    # Results are historical training data; scheduled fixtures are
                    # deliberately kept to the same seven-day horizon as odds.
                    if status == 'scheduled' and not observed < kickoff <= fixture_cutoff:
                        continue
                    match_id = ingest_match(
                        connection, SOURCE, f'{competition_info.code}:{source_id}', competition_info.code, home, away, kickoff, confirmed,
                        status, stats, observed,
                    )
                except (KeyError, TypeError, ValueError) as error:
                    quarantine(connection, SOURCE, str(error), match)
                    continue
                if match_id:
                    # Rosters are only requested for finalised matches and only
                    # until a successful player-stat import exists.  They label
                    # historical XIs; never infer an upcoming lineup from them.
                    if status == 'finished' and not connection.execute('SELECT 1 FROM player_match_stats WHERE match_id=? LIMIT 1', (match_id,)).fetchone():
                        try:
                            save_roster(connection, match_id, client.match(match=str(source_id)).get_roster_data(timeout=REQUEST_TIMEOUT))
                        except Exception as error:  # Provider outages must not block scores.
                            quarantine(connection, SOURCE, f'Roster import failed: {error}', {'match_id': source_id})
                    imported += 1
    return imported


def import_results(connection, league, seasons, client_factory=UnderstatClient):
    """Import one supported league's completed results and player observations.

    The roster is stored against its own completed fixture.  Feature builders
    later filter those observations by kickoff, so walk-forward fitting cannot
    see a player's target-match or future performance.
    """
    competition_info = competition(league)
    imported = 0
    with client_factory() as client:
        endpoint = client.league(league=competition_info.understat)
        for season in seasons:
            for match in endpoint.get_match_data(season=str(season), timeout=REQUEST_TIMEOUT):
                if not match.get('isResult'):
                    continue
                try:
                    source_id, home, away, kickoff, confirmed, status, stats = _match_fields(match)
                    match_id = ingest_match(
                        connection, SOURCE, f'{competition_info.code}:{source_id}', competition_info.code, home, away, kickoff, confirmed,
                        status, stats, now(),
                    )
                except (KeyError, TypeError, ValueError) as error:
                    quarantine(connection, SOURCE, str(error), match)
                    continue
                if match_id:
                    if not connection.execute('SELECT 1 FROM player_match_stats WHERE match_id=? LIMIT 1', (match_id,)).fetchone():
                        try:
                            save_roster(connection, match_id, client.match(match=str(source_id)).get_roster_data(timeout=REQUEST_TIMEOUT))
                        except Exception as error:
                            quarantine(connection, SOURCE, f'Roster import failed: {error}', {'match_id': source_id})
                    imported += 1
    return imported


# Compatibility aliases for callers and saved automation that previously named EPL.
def sync_epl_seasons(connection, seasons, client_factory=UnderstatClient, observed=None):
    return sync_seasons(connection, 'E0', seasons, client_factory, observed)


def import_epl_results(connection, seasons, client_factory=UnderstatClient):
    return import_results(connection, 'E0', seasons, client_factory)
