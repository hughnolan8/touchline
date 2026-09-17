"""Explicit, one-time reset of the Railway football simulation data."""
from backend.db import set_setting


def reset_simulation_data(connection):
    """Delete football-derived data while retaining database configuration."""
    for table in ('bets', 'predictions', 'models', 'quotes', 'lineup_snapshots', 'player_match_stats', 'player_aliases',
                  'players', 'observations', 'match_aliases', 'aliases', 'matches', 'teams', 'snapshots', 'sources', 'quarantine'):
        connection.execute(f'DELETE FROM {table}')
    connection.execute(
        "DELETE FROM settings WHERE key IN ('bootstrap_complete', 'last_engine_success', 'last_manual_refresh', 'last_odds_refresh', 'odds_api_quota') OR key LIKE ? OR key LIKE ?",
        ('refreshed:%', 'lineup-refreshed:%'),
    )
    set_setting(connection, 'understat_cutover_complete', True)
