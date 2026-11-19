#!/usr/bin/env python3
"""Explicit operator promotion for a validated Touchline forecaster."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db import connect, setting, set_setting, init
from backend.competitions import BY_CODE

parser = argparse.ArgumentParser(description='Promote an eligible model version')
parser.add_argument('--model', choices=('baseline-v1', 'xi-v2'), required=True)
parser.add_argument('--league', choices=tuple(BY_CODE), required=True)
args = parser.parse_args()
init()
with connect() as connection:
    if args.model != 'baseline-v1':
        evaluation = connection.execute('SELECT * FROM model_evaluations WHERE model_version=? ORDER BY id DESC LIMIT 1', (f'{args.league}:{args.model}',)).fetchone()
        if not evaluation or not evaluation['eligible']:
            raise SystemExit(f'{args.model} has no eligible evaluation; run scripts/backtest.py and complete prospective validation')
    strategy = setting(connection, f'strategy:{args.league}', setting(connection, 'strategy'))
    set_setting(connection, f'strategy:{args.league}', {**strategy, 'active_model': args.model, 'version': strategy.get('version', 1) + 1})
print(f'promoted {args.model} for {args.league}')
