#!/usr/bin/env python3
"""Reset Railway's football simulation data for the Understat datasource cutover."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.db import connect, init
from backend.app.reset import reset_simulation_data


def main():
    parser = argparse.ArgumentParser(description='Delete Railway football, model, prediction, and paper-ledger data')
    parser.add_argument('--confirm', action='store_true', help='perform the irreversible reset')
    args = parser.parse_args()
    if not args.confirm:
        parser.error('pass --confirm to reset Railway simulation data')
    if not os.environ.get('DATABASE_URL'):
        parser.error('DATABASE_URL is required; execute this inside the Railway engine service with railway ssh')
    init()
    with connect() as connection:
        reset_simulation_data(connection)
    print('Railway simulation data reset. The next engine run will bootstrap Understat seasons.')


if __name__ == '__main__':
    main()
