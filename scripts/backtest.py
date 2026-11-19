#!/usr/bin/env python3
"""Run the score-only, walk-forward Dixon--Coles backtest for a local database."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Support the documented `python scripts/backtest.py` invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.backtest import evaluate_candidate, summary, walk_forward, walk_forward_player
from backend.db import connect, init
from backend.understat import import_results
from backend.competitions import COMPETITIONS, BY_CODE


def main():
    parser = argparse.ArgumentParser(description='Score-only, walk-forward Dixon--Coles backtest')
    parser.add_argument('--start-season', type=int, default=2021, help='first season start-year to import')
    parser.add_argument('--end-season', type=int, default=datetime.now().year, help='last season start-year to import')
    parser.add_argument('--skip-import', action='store_true', help='use results already in the configured database')
    parser.add_argument('--retrain-days', type=int, default=1, help='reuse each fit for this many calendar days (default: every day)')
    parser.add_argument('--league', choices=tuple(BY_CODE), help='backtest one league; default is all supported leagues')
    args = parser.parse_args()
    if args.start_season > args.end_season:
        parser.error('--start-season cannot be later than --end-season')
    init()
    # Commit the downloaded historical results before the comparatively long
    # walk-forward fit. This makes an interrupted evaluation resumable with
    # --skip-import instead of losing the import transaction.
    with connect() as connection:
        leagues=(args.league,) if args.league else tuple(item.code for item in COMPETITIONS)
        imported={league: 0 if args.skip_import else import_results(connection, league, range(args.start_season, args.end_season + 1)) for league in leagues}
    with connect() as connection:
        report={league:{'baseline':summary(walk_forward(connection, retrain_days=args.retrain_days, league=league)),'confirmed_xi':summary(walk_forward_player(connection, retrain_days=args.retrain_days, league=league)),'candidate_evaluation':evaluate_candidate(connection, retrain_days=args.retrain_days, league=league),'imported_results':imported[league],'retrain_days':args.retrain_days} for league in leagues}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
