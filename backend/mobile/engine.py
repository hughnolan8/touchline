"""Resumable, budgeted simulation runner for the independent mobile service."""
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta
from urllib.robotparser import RobotFileParser
from backend.db import connect, rows, now, dump, setting, set_setting
from backend.engine import (history, generate_predictions, opportunities, place_bet, settle,
                            portfolios, seconds)
from backend.models import evaluate, fit_dc
from backend.providers import PublicFiles, football_csv
from .provider import MobileOdds
from .store import transaction, acquire, release, LEAGUES, DATA_DEFAULTS


def enqueue(c, key, kind, payload, priority, at):
    c.execute('INSERT OR IGNORE INTO mobile_jobs(id,kind,payload,priority,available_at) VALUES(?,?,?,?,?)',
              (key, kind, dump(payload), priority, at))


def schedule(at):
    dt = datetime.fromisoformat(at)
    year = dt.year if dt.month >= 7 else dt.year - 1
    six_hour = int(dt.timestamp()) // 21600
    with transaction() as c:
        cfg = {**DATA_DEFAULTS, **setting(c, 'odds_api_config', {})}
        if cfg['auto_refresh'] and os.environ.get('MOBILE_ODDS_API_KEY'):
            enqueue(c, f'quota:{six_hour}', 'quota', {}, -1, at)
        for comp in LEAGUES:
            # Bootstrap each file separately; failed downloads have a finite retry cycle.
            for yr in range(year - 3, year + 1):
                season = f'{yr % 100:02}{(yr + 1) % 100:02}'
                enqueue(c, f'archive:{comp}:{season}', 'file',
                        {'url': f'https://www.football-data.co.uk/mmz4281/{season}/{comp}.csv'}, 40, at)
            season = f'{year % 100:02}{(year + 1) % 100:02}'
            enqueue(c, f'current:{comp}:{six_hour}', 'file',
                    {'url': f'https://www.football-data.co.uk/mmz4281/{season}/{comp}.csv'}, 30, at)
            archive_pending = c.execute("SELECT 1 FROM mobile_jobs WHERE id LIKE ? AND status IN ('queued','running') LIMIT 1", (f'archive:{comp}:%',)).fetchone()
            if not archive_pending:
                enqueue(c, f'train:{comp}:{int(dt.timestamp()) // (7 * 86400)}', 'train', {'competition': comp}, 35, at)
            if not cfg['auto_refresh'] or not os.environ.get('MOBILE_ODDS_API_KEY'):
                continue
            outstanding = c.execute("SELECT 1 FROM bets b JOIN matches m ON m.id=b.match_id WHERE b.status IN ('open','review') AND m.competition=? AND m.kickoff<? LIMIT 1",
                                    (comp, (dt - timedelta(minutes=100)).isoformat())).fetchone()
            if outstanding:
                enqueue(c, f'scores:{comp}:{int(dt.timestamp()) // 1800}', 'scores', {'competition': comp}, 0, at)
            active = c.execute("SELECT 1 FROM matches WHERE competition=? AND status='scheduled' AND kickoff>? AND kickoff<? LIMIT 1",
                               (comp, at, (dt + timedelta(minutes=90)).isoformat())).fetchone()
            bucket = int(dt.timestamp()) // (cfg['interval_minutes'] * 60) if active else six_hour
            enqueue(c, f'odds:{comp}:{"active" if active else "discovery"}:{bucket}', 'odds', {'competition': comp}, 10 if active else 20, at)
        enqueue(c, f'fixtures:{six_hour}', 'file', {'url': 'https://www.football-data.co.uk/fixtures.csv'}, 25, at)
        # Bounded retention for completed periodic work; archive checkpoints are permanent.
        cutoff = (dt - timedelta(days=14)).isoformat()
        c.execute("DELETE FROM mobile_jobs WHERE status IN ('done','failed','superseded') AND finished_at<? AND id NOT LIKE ?", (cutoff, 'archive:%'))
        # Revisit unavailable archive files once per day rather than needing a manual reset.
        c.execute("UPDATE mobile_jobs SET status='queued',attempts=0 WHERE status='failed' AND id LIKE ? AND available_at<=?", ('archive:%', at))


def claim(at, training=None, lease_seconds=280):
    with transaction() as c:
        c.execute("UPDATE mobile_jobs SET status='failed',finished_at=?,available_at=?,message='Repeated process interruption; retry on the next maintenance cycle' WHERE status='running' AND lease_until<=? AND attempts>=3",
                  (at, (datetime.fromisoformat(at)+timedelta(days=1)).isoformat(), at))
        c.execute("UPDATE mobile_jobs SET status='queued',message='Recovered after interrupted run' WHERE status='running' AND lease_until<=?", (at,))
        # Old odds/scores tasks must not drain credits in a catch-up storm.
        cutoff = (datetime.fromisoformat(at) - timedelta(minutes=30)).isoformat()
        c.execute("UPDATE mobile_jobs SET status='superseded',finished_at=? WHERE kind IN ('odds','scores') AND status='queued' AND available_at<?", (at, cutoff))
        kind_filter = " AND kind='train'" if training is True else " AND kind!='train'" if training is False else ""
        job = c.execute("SELECT * FROM mobile_jobs WHERE status='queued' AND available_at<=?" + kind_filter + " ORDER BY priority,available_at,id LIMIT 1", (at,)).fetchone()
        if not job:
            return None
        c.execute("UPDATE mobile_jobs SET status='running',attempts=attempts+1,lease_until=? WHERE id=?", ((datetime.fromisoformat(at)+timedelta(seconds=lease_seconds)).isoformat(), job['id']))
        return dict(job)


def run_job(job):
    payload = json.loads(job['payload'])
    if job['kind'] in ('odds', 'scores', 'quota'):
        provider = MobileOdds()
        try:
            if job['kind'] == 'quota':
                return provider.quota()
            return getattr(provider, job['kind'])(payload['competition'])
        finally:
            provider.close()
    if job['kind'] == 'file':
        provider = PublicFiles()
        try:
            r = provider.client.get('https://www.football-data.co.uk/robots.txt')
            r.raise_for_status()
            robots = RobotFileParser()
            robots.parse(r.text.splitlines())
            if not robots.can_fetch('TouchlineResearch', payload['url']):
                raise ValueError('Public source collection is unavailable under its access rules')
            with connect() as c:
                count = provider.fetch(c, payload['url'], 'football-data', football_csv)
                status = c.execute('SELECT status FROM sources WHERE id=?', (payload['url'],)).fetchone()
            if not status or status['status'] != 'ok':
                raise ValueError('Public source temporarily unavailable')
            return f'{count} source records processed'
        finally:
            provider.client.close()
    if job['kind'] == 'train':
        comp = payload['competition']
        cutoff = now()
        with connect() as c:
            records = history(c, comp, cutoff)
        if len(records) < 160:
            raise ValueError('Awaiting at least 160 completed matches for training')
        metrics, selected = evaluate(records, cutoff)
        model = {'dc': fit_dc(records, cutoff), 'selected': selected, 'history_ids': [r['id'] for r in records]}
        with connect() as c:
            c.execute('INSERT INTO models(competition,created_at,cutoff,samples,payload,metrics) VALUES(?,?,?,?,?,?)',
                      (comp, now(), cutoff, len(records), dump(model), dump(metrics)))
        return f'{comp} model trained on {len(records)} matches'
    raise ValueError('Unsupported job')


def complete(job, error=None, message=None):
    at = now()
    attempts = job['attempts'] + 1
    retry = (datetime.fromisoformat(at) + timedelta(minutes=5 * 2**min(attempts - 1, 4))).isoformat()
    state = 'done' if error is None else 'failed' if attempts >= 3 else 'queued'
    if state == 'failed':
        retry = (datetime.fromisoformat(at) + timedelta(days=1)).isoformat()
    # Never persist raw exception text: a transport exception can contain an API key.
    safe = message if error is None else (str(error) if isinstance(error, ValueError) else 'Job failed; automatic retry scheduled. Check provider and source status.')
    from backend.odds_api import OddsApiError
    if isinstance(error, OddsApiError):
        safe = str(error)
    with connect() as c:
        c.execute('UPDATE mobile_jobs SET status=?,available_at=?,finished_at=?,message=?,lease_until=NULL WHERE id=?',
                  (state, retry if error else at, at if state in ('done', 'failed') else None, safe, job['id']))


def select_automatic(at=None):
    at = at or now()
    count = 0
    reasons = Counter()
    with transaction() as c:
        candidates = opportunities(c, at, include_indicative=True)
        config = setting(c, 'strategy')
        for candidate in candidates:
            if candidate['competition'] not in LEAGUES or candidate['market'] not in ('1x2', 'goals'):
                reasons['Unsupported competition or market'] += 1
                continue
            if not candidate['eligible']:
                for reason in candidate['reasons']:
                    reasons[reason] += 1
                continue
            minutes = seconds(candidate['kickoff'], at) / 60
            if not config['enabled']:
                reasons['Automatic entries paused'] += 1
                continue
            if not config['window_end'] <= minutes <= config['window_start']:
                reasons['Outside automatic entry window'] += 1
                continue
            if candidate['edge'] < config['min_edge']:
                reasons['Below minimum estimated edge'] += 1
                continue
            if candidate['age_minutes'] > config['max_quote_age']:
                reasons['Quote exceeds strategy age limit'] += 1
                continue
            if c.execute("SELECT 1 FROM bets WHERE portfolio='automatic' AND match_id=?", (candidate['match_id'],)).fetchone():
                reasons['Fixture already recorded'] += 1
                continue
            try:
                place_bet(c, candidate['id'], 'automatic', at)
                count += 1
            except ValueError as exc:
                reasons[str(exc)] += 1
        set_setting(c, 'mobile_decisions', {'at': at, 'recorded': count, 'reasons': dict(reasons)})
    return count


def tick(max_seconds=200, max_jobs=8, include_training=True):
    token = acquire('tick')
    if not token:
        return {'ok': True, 'skipped': True, 'reason': 'Another run owns the lease'}
    started = time.monotonic()
    errors = 0
    processed = 0
    try:
        with connect() as c:
            set_setting(c, 'mobile_last_attempt', now())
            set_setting(c, 'mobile_provider_configured', bool(os.environ.get('MOBILE_ODDS_API_KEY')))
        schedule(now())
        # Entry checks happen before maintenance and after updated data arrives.
        generate_predictions()
        select_automatic()
        settle()
        while processed < max_jobs and time.monotonic() - started < max_seconds:
            job = claim(now(), training=None if include_training else False)
            if not job:
                break
            # Do not start model fitting near the function's deadline.
            if job['kind'] == 'train' and time.monotonic() - started > 30:
                with connect() as c:
                    c.execute("UPDATE mobile_jobs SET status='queued',attempts=attempts-1,lease_until=NULL WHERE id=?", (job['id'],))
                break
            try:
                message = run_job(job)
                complete(job, message=message)
            except Exception as exc:
                complete(job, error=exc)
                errors += 1
            processed += 1
            if job['kind'] in ('odds', 'scores', 'train'):
                generate_predictions()
                select_automatic()
                settle()
        with connect() as c:
            set_setting(c, 'mobile_last_success', now())
            set_setting(c, 'mobile_last_run', {'jobs': processed, 'errors': errors, 'duration_seconds': round(time.monotonic() - started, 2)})
        return {'ok': True, 'jobs': processed, 'errors': errors}
    finally:
        release('tick', token)


def training_tick():
    """One isolated training job. The supervisor kills work before the lease expires."""
    token = acquire('training', seconds=960)
    if not token:
        return {'ok': True, 'skipped': True}
    try:
        job = claim(now(), training=True, lease_seconds=960)
        if not job:
            return {'ok': True, 'jobs': 0, 'errors': 0}
        try:
            complete(job, message=run_job(job))
        except Exception as exc:
            complete(job, error=exc)
            return {'ok': True, 'jobs': 1, 'errors': 1}
        return {'ok': True, 'jobs': 1, 'errors': 0}
    finally:
        release('training', token)
