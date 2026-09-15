"""Deploy only the iOS backend to the linked Railway project. Never resets data."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--service', choices=['api', 'engine', 'trainer', 'all'], default='all')
args = parser.parse_args()
cli = os.environ.get('RAILWAY_CLI') or shutil.which('railway')
if not cli:
    raise SystemExit('Install the official Railway CLI and run railway login first.')
config = json.loads((root / 'data/mobile/railway.json').read_text())
for service in (['api', 'engine', 'trainer'] if args.service == 'all' else [args.service]):
    subprocess.run([cli, 'up', '--detach', '--json', '--project', config['project_id'],
                    '--environment', config['environment_id'], '--service', config['services'][service]], cwd=root, check=True)
print('Deployments submitted. Check Railway deployment status, then run scripts/check-mobile-live.py --require-fresh.')
