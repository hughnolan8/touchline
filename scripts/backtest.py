#!/usr/bin/env python3
"""Run the score-only, walk-forward Dixon--Coles backtest for a local database."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Support the documented `python scripts/backtest.py` invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.backtest import summary, walk_forward
from backend.db import connect, init
from backend.understat import import_epl_results


def main():
    parser = argparse.ArgumentParser(description='Score-only, walk-forward Dixon--Coles backtest')
    parser.add_argument('--start-season', type=int, default=2021, help='first season start-year to import')
    parser.add_argument('--end-season', type=int, default=datetime.now().year, help='last season start-year to import')
    parser.add_argument('--skip-import', action='store_true', help='use results already in the configured database')
    parser.add_argument('--retrain-days', type=int, default=1, help='reuse each fit for this many calendar days (default: every day)')
    args = parser.parse_args()
    if args.start_season > args.end_season:
        parser.error('--start-season cannot be later than --end-season')
    init()
    # Commit the downloaded historical results before the comparatively long
    # walk-forward fit. This makes an interrupted evaluation resumable with
    # --skip-import instead of losing the import transaction.
    with connect() as connection:
        imported = 0 if args.skip_import else import_epl_results(connection, range(args.start_season, args.end_season + 1))
    with connect() as connection:
        report = summary(walk_forward(connection, retrain_days=args.retrain_days))
    report['imported_results'] = imported
    report['retrain_days'] = args.retrain_days
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
