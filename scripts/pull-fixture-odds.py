#!/usr/bin/env python3
"""Request The Odds API prices for one fixture using an isolated local database."""
import argparse
import json
import os
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


parser = argparse.ArgumentParser()
parser.add_argument('--api-key', required=True, help='The Odds API key')
parser.add_argument('--home', required=True, help='Home team name')
parser.add_argument('--away', required=True, help='Away team name')
parser.add_argument('--kickoff', required=True, help='ISO-8601 kick-off with timezone')
parser.add_argument('--at', help='Optional ISO-8601 current time with timezone')
args = parser.parse_args()

os.environ['TOUCHLINE_ODDS_API_KEY'] = args.api_key
os.environ.pop('DATABASE_URL', None)

with tempfile.TemporaryDirectory(prefix='touchline-odds-') as directory:
    os.environ['ENGINE_DB'] = f'{directory}/engine.sqlite3'
    from backend.db import connect, now, stamp
    from backend.app.provider import MobileOdds
    from backend.app.store import initialize
    from backend.providers import ingest_match

    at = stamp(args.at or now())
    kickoff = stamp(args.kickoff)
    initialize()
    with connect() as connection:
        fixture = ingest_match(
            connection, 'manual-test', 'fixture', 'E0', args.home, args.away,
            kickoff, True, 'scheduled', {}, at,
        )
        match = dict(connection.execute('SELECT * FROM matches WHERE id=?', (fixture,)).fetchone())
    odds = MobileOdds()
    try:
        imported = odds.refresh([match], at)
    finally:
        odds.close()
    with connect() as connection:
        quotes = [dict(row) for row in connection.execute(
            'SELECT selection,bookmaker,odds,quoted_at FROM quotes WHERE match_id=? ORDER BY bookmaker,selection',
            (fixture,),
        )]
    print(json.dumps({'fixture': f'{args.home} vs {args.away}', 'imported': imported, 'quotes': quotes}, indent=2))
