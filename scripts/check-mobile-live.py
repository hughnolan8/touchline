"""Read-only live checks for the Railway API and autonomous engine."""
import argparse
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--require-fresh', action='store_true', help='Fail unless a tick completed within 15 minutes')
args = parser.parse_args()
config = json.loads((Path(__file__).resolve().parents[1]/'data/mobile/railway.json').read_text())
base = config['mobile_api_url'].rstrip('/')
token = os.environ.get('MOBILE_OWNER_TOKEN')
if not token:
    cli = os.environ.get('RAILWAY_CLI') or shutil.which('railway')
    if not cli:
        raise SystemExit('Set MOBILE_OWNER_TOKEN or install the Railway CLI and run `railway login`.')
    try:
        result = subprocess.run(
            [cli, 'variable', 'list', '--kv', '--project', config['project_id'],
             '--environment', config['environment_id'], '--service', config['services']['api']],
            capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        raise SystemExit('Unable to read the Railway API variables. Run `railway login` and try again.')
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    token = values.get('MOBILE_OWNER_TOKEN')
if not token:
    raise SystemExit('MOBILE_OWNER_TOKEN is not configured on the Railway api service.')
with httpx.Client(timeout=40, follow_redirects=False) as client:
    health = client.get(base+'/health')
    print('Health:', health.status_code)
    if health.status_code != 200:
        print('Backend unavailable; automatic operation is not verified.')
        raise SystemExit(1)
    assert health.json()['service'] == 'touchline-mobile'
    assert client.get(base+'/api/v1/summary').status_code == 401
    response = client.get(base+'/api/v1/summary', headers={'Authorization': 'Bearer '+token})
    response.raise_for_status()
    summary = response.json()
    engine = summary['engine']
    print('Mode:', summary['mode'], 'Engine:', engine['status'])
    print('Last automatic completion:', engine['last_success'])
    print('Trained leagues:', ', '.join(engine['trained_leagues']) or 'none')
    if engine['status'] in ('degraded', 'overdue'):
        print('Recent worker jobs:')
        for job in engine['jobs']:
            if job['status'] != 'done' or job['message']:
                print(f"- {job['id']}: {job['status']} ({job['message'] or 'no message'})")
    if args.require_fresh:
        last = datetime.fromisoformat(engine['last_success']) if engine['last_success'] else None
        assert last and 0 <= (datetime.now(timezone.utc)-last).total_seconds() <= 900, 'Automatic engine heartbeat is overdue'
        assert engine['status'] not in ('degraded', 'overdue'), 'Engine requires attention'
