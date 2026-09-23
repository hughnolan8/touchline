"""Read-only public production health check for GitHub Actions."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def fetch(url):
    try:
        with urlopen(url, timeout=20) as response:
            return response.status, json.load(response), None
    except HTTPError as error:
        return error.code, None, 'http_error'
    except (URLError, TimeoutError, json.JSONDecodeError):
        return None, None, 'unavailable'


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except (AttributeError, ValueError):
        return None


def check(base_url, started_at, request=fetch):
    results = {}
    for name, path in {'api': '/health', 'engine': '/health/engine', 'summary': '/api/v1/summary'}.items():
        status, body, error = request(base_url + path)
        results[name] = {'status': status, 'error': error}
        if body is not None:
            results[name]['body'] = body
    api = results['api'].get('body')
    engine = results['engine'].get('body')
    summary = results['summary'].get('body')
    problems = []
    if results['api']['status'] != 200 or not isinstance(api, dict) or api.get('ok') is not True:
        problems.append('API health check is unhealthy')
    if results['engine']['status'] != 200 or not isinstance(engine, dict) or engine.get('ok') is not True:
        problems.append('Engine health check is unhealthy')
    engine_summary = summary.get('engine') if isinstance(summary, dict) else None
    status = engine_summary.get('status') if isinstance(engine_summary, dict) else None
    last_success = timestamp(engine_summary.get('last_success')) if isinstance(engine_summary, dict) else None
    if results['summary']['status'] != 200 or not isinstance(summary, dict) or summary.get('mode') != 'paper':
        problems.append('Summary is unavailable or not in paper mode')
    if status != 'running':
        problems.append('Engine summary status is not running')
    if last_success is None or last_success <= started_at:
        problems.append('Engine has not completed a fresh cycle')
    return results, problems, last_success


def monitor(base_url, timeout_seconds=600, interval_seconds=60, request=fetch, clock=lambda: datetime.now(timezone.utc), wait=sleep, timer=monotonic):
    started_at = clock()
    deadline = timer() + timeout_seconds
    while True:
        results, problems, last_success = check(base_url, started_at, request)
        if not problems:
            return True, results, [], last_success
        if timer() >= deadline:
            return False, results, problems, last_success
        wait(min(interval_seconds, max(0, deadline - timer())))


def report(ok, results, problems, last_success):
    lines = ['## Production support check', '', f"**Result:** {'pass' if ok else 'fail'}", '']
    for name in ('api', 'engine', 'summary'):
        result = results[name]
        detail = str(result['status']) if result['status'] is not None else result.get('error', 'unavailable')
        lines.append(f'- {name}: {detail}')
    lines.append(f"- fresh engine success: {last_success.isoformat() if last_success else 'not observed'}")
    if problems:
        lines.extend(['', '**Findings:**'] + [f'- {problem}' for problem in problems])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[1] / 'data/runtime/railway.json')
    parser.add_argument('--timeout-seconds', type=int, default=600)
    parser.add_argument('--interval-seconds', type=int, default=60)
    args = parser.parse_args()
    if args.timeout_seconds < 0 or args.interval_seconds <= 0:
        parser.error('timeout must be non-negative and interval must be positive')
    base_url = json.loads(args.config.read_text())['mobile_api_url'].rstrip('/')
    ok, results, problems, last_success = monitor(base_url, args.timeout_seconds, args.interval_seconds)
    print(report(ok, results, problems, last_success))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
