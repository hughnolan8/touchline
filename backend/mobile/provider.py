"""Budgeted requests with durable accounting per attempt, including network failures."""
import hashlib
import json
import math
import os
from datetime import datetime, timedelta
import httpx
from backend.db import connect, now, setting, set_setting, dump, quarantine
from backend.odds_api import OddsApiError, SPORTS, parse_events
from backend.providers import ingest_match
from .store import transaction, DATA_DEFAULTS, LEAGUES


class MobileOdds:
    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=20)

    def close(self):
        self.client.close()

    def request(self, route, params, cost=2):
        key = os.environ.get('MOBILE_ODDS_API_KEY', '')
        if not key:
            raise OddsApiError('Configure the mobile Odds API key to collect current data.')
        with transaction() as c:
            cfg = {**DATA_DEFAULTS, **setting(c, 'odds_api_config', {})}
            daily = setting(c, 'odds_api_daily', {})
            if daily.get('date') != now()[:10]:
                daily = {'date': now()[:10], 'credits': 0}
            quota = setting(c, 'odds_api_quota', {})
            if cost and daily['credits'] + cost > cfg['daily_credit_limit']:
                raise OddsApiError('Daily API credit budget reached; awaiting the next UTC day.')
            if cost and quota.get('remaining', float('inf')) < cfg['quota_reserve'] + cost:
                raise OddsApiError('Provider quota reserve reached; awaiting available credits.')
            # Charge before I/O: a process death cannot erase the cost of a request.
            daily['credits'] += cost
            set_setting(c, 'odds_api_daily', daily)
            if 'remaining' in quota:
                quota['remaining'] = max(0, quota['remaining'] - cost)
                set_setting(c, 'odds_api_quota', quota)
        try:
            response = self.client.get('https://api.the-odds-api.com/v4' + route,
                                       params={'apiKey': key, **params})
        except httpx.HTTPError:
            raise OddsApiError('Provider connection failed; request allowance retained and job will retry.') from None
        observed = now()
        with transaction() as c:
            quota = setting(c, 'odds_api_quota', {})
            quota['last_cost'] = cost
            for name, header in [('remaining', 'x-requests-remaining'), ('used', 'x-requests-used'), ('last_cost', 'x-requests-last')]:
                try:
                    value = float(response.headers[header])
                    if math.isfinite(value) and value >= 0:
                        quota[name] = value
                except (KeyError, ValueError):
                    pass
            quota['checked_at'] = observed
            set_setting(c, 'odds_api_quota', quota)
            # Keep conservative reservations; account for unexpectedly higher charges.
            if quota.get('last_cost', cost) > cost:
                daily = setting(c, 'odds_api_daily')
                if daily['date'] == observed[:10]:
                    daily['credits'] += quota['last_cost'] - cost
                    set_setting(c, 'odds_api_daily', daily)
        if response.status_code != 200:
            raise OddsApiError(f'Provider returned HTTP {response.status_code}; collection will retry within the budget.')
        try:
            events = response.json()
        except ValueError:
            raise OddsApiError('Provider returned invalid JSON.') from None
        if not isinstance(events, list):
            raise OddsApiError('Provider returned an unexpected event format.')
        with connect() as c:
            body = dump(events)
            c.execute('INSERT OR IGNORE INTO snapshots(source,url,observed_at,content_hash,body) VALUES(?,?,?,?,?)',
                      ('mobile-odds-api', 'https://api.the-odds-api.com/v4' + route, observed,
                       hashlib.sha256(body.encode()).hexdigest(), body))
        return events, observed

    def quota(self):
        self.request('/sports', {'all': 'true'}, cost=0)
        return 'Provider quota refreshed without spending odds credits'

    def odds(self, competition):
        at = datetime.fromisoformat(now())
        events, observed = self.request(f'/sports/{SPORTS[competition]}/odds', {
            'regions': 'uk', 'markets': 'h2h,totals', 'oddsFormat': 'decimal',
            'dateFormat': 'iso', 'commenceTimeFrom': at.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'commenceTimeTo': (at + timedelta(days=14)).strftime('%Y-%m-%dT%H:%M:%SZ')})
        with connect() as c:
            count = parse_events(c, events, competition, observed)
            set_setting(c, 'mobile_odds_' + competition, observed)
        return f'{count} fixtures with odds collected'

    def scores(self, competition):
        events, observed = self.request(f'/sports/{SPORTS[competition]}/scores', {'daysFrom': 3, 'dateFormat': 'iso'})
        with connect() as c:
            count = ingest_scores(c, events, competition, observed)
        return f'{count} verified results collected'


def ingest_scores(c, events, competition, observed):
    if competition not in LEAGUES:
        raise ValueError('Only regulation-time domestic league results are supported')
    count = 0
    for event in events:
        c.execute('SAVEPOINT mobile_score')
        try:
            if not isinstance(event, dict):
                raise ValueError('Invalid event')
            if event.get('completed') is not True:
                c.execute('RELEASE mobile_score')
                continue
            # Use exact provider identity and existing teams; never invent a match from a score.
            match = c.execute('''SELECT m.*,h.name home_name,a.name away_name FROM matches m
                JOIN match_aliases x ON x.match_id=m.id JOIN teams h ON h.id=m.home
                JOIN teams a ON a.id=m.away WHERE x.source='the-odds-api' AND x.source_id=?''',
                (event['id'],)).fetchone()
            if not match or match['competition'] != competition:
                c.execute('RELEASE mobile_score')
                continue
            if match['kickoff'] >= observed:
                raise ValueError('Completed result precedes kickoff')
            scores = event.get('scores') or []
            if len(scores) != 2:
                raise ValueError('Incomplete score')
            values = {s['name']: int(s['score']) for s in scores if str(s.get('score', '')).isdigit()}
            if set(values) != {event['home_team'], event['away_team']}:
                raise ValueError('Scores do not match event participants')
            from backend.providers import norm, ALIASES
            if norm(ALIASES.get(event['home_team'], event['home_team'])) != match['home'] or norm(ALIASES.get(event['away_team'], event['away_team'])) != match['away']:
                raise ValueError('Result teams conflict with fixture')
            stats = {'hg': values[event['home_team']], 'ag': values[event['away_team']]}
            result = ingest_match(c, 'the-odds-api', event['id'], competition,
                                  event['home_team'], event['away_team'], match['kickoff'], True,
                                  'finished', stats, observed)
            if result:
                count += 1
            c.execute('RELEASE mobile_score')
        except (ValueError, KeyError, TypeError):
            c.execute('ROLLBACK TO mobile_score')
            c.execute('RELEASE mobile_score')
            quarantine(c, 'mobile-scores', 'Invalid or conflicting completed result', event)
    return count
