"""Premier League fixture and result imports from Understat via understatapi."""
from datetime import datetime, timezone

from understatapi import UnderstatClient

from .db import now, quarantine
from .providers import ingest_match


SOURCE = 'understat'
LEAGUE = 'EPL'
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


def sync_epl_seasons(connection, seasons, client_factory=UnderstatClient, observed=None):
    """Import Understat EPL fixtures for season start-years, returning their count.

    The league endpoint supplies both upcoming fixtures and completed results.
    Only completed records carry final scores; no xG, forecasts, or odds are
    imported into Touchline.
    """
    imported = 0
    observed = observed or now()
    with client_factory() as client:
        endpoint = client.league(league=LEAGUE)
        for season in seasons:
            for match in endpoint.get_match_data(season=str(season), timeout=REQUEST_TIMEOUT):
                try:
                    source_id, home, away, kickoff, confirmed, status, stats = _match_fields(match)
                    if status == 'finished' and kickoff > observed:
                        raise ValueError('Result appears before kickoff')
                    match_id = ingest_match(
                        connection, SOURCE, source_id, 'E0', home, away, kickoff, confirmed,
                        status, stats, observed,
                    )
                except (KeyError, TypeError, ValueError) as error:
                    quarantine(connection, SOURCE, str(error), match)
                    continue
                if match_id:
                    imported += 1
    return imported


def import_epl_results(connection, seasons, client_factory=UnderstatClient):
    """Import only completed EPL results for the score-only backtest."""
    imported = 0
    with client_factory() as client:
        endpoint = client.league(league=LEAGUE)
        for season in seasons:
            for match in endpoint.get_match_data(season=str(season), timeout=REQUEST_TIMEOUT):
                if not match.get('isResult'):
                    continue
                try:
                    source_id, home, away, kickoff, confirmed, status, stats = _match_fields(match)
                    match_id = ingest_match(
                        connection, SOURCE, source_id, 'E0', home, away, kickoff, confirmed,
                        status, stats, now(),
                    )
                except (KeyError, TypeError, ValueError) as error:
                    quarantine(connection, SOURCE, str(error), match)
                    continue
                if match_id:
                    imported += 1
    return imported
