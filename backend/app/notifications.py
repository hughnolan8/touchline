"""Optional, retry-safe Pushover delivery for placed paper bets."""
import json
import logging
import os

import httpx

from backend.db import connect, now, rows

PUSHOVER_URL = 'https://api.pushover.net/1/messages.json'


def configured():
    return bool(os.environ.get('PUSHOVER_APP_TOKEN') and os.environ.get('PUSHOVER_USER_KEY'))


def _message(item):
    bet = json.loads(item['snapshot'])
    return '\n'.join((
        f"{item['home_name']} vs {item['away_name']}",
        f"{bet['selection'].title()} @ {bet['odds']:.2f} ({bet['bookmaker']})",
        f"Stake £{item['stake']:.2f} · Edge {bet['edge'] * 100:.1f}%",
    ))


def deliver_pending_bet_notifications():
    """Try every queued alert once; delivery never affects the betting ledger."""
    if not configured():
        return 0
    with connect() as c:
        pending = rows(c, '''SELECT n.bet_id,b.stake,b.snapshot,h.name home_name,a.name away_name
          FROM bet_notifications n JOIN bets b ON b.id=n.bet_id
          JOIN matches m ON m.id=b.match_id JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away
          WHERE n.status='pending' ORDER BY n.bet_id''')
    sent = 0
    for item in pending:
        payload = {'token': os.environ['PUSHOVER_APP_TOKEN'], 'user': os.environ['PUSHOVER_USER_KEY'],
                   'title': 'Touchline bet placed', 'message': _message(item), 'priority': 0}
        if os.environ.get('PUSHOVER_DEVICE'):
            payload['device'] = os.environ['PUSHOVER_DEVICE']
        if os.environ.get('PUSHOVER_DASHBOARD_URL'):
            payload.update(url=os.environ['PUSHOVER_DASHBOARD_URL'], url_title='Open Touchline')
        try:
            response = httpx.post(PUSHOVER_URL, data=payload, timeout=10)
            response.raise_for_status()
        except httpx.HTTPError as error:
            with connect() as c:
                c.execute("UPDATE bet_notifications SET attempts=attempts+1,last_error=? WHERE bet_id=? AND status='pending'", (type(error).__name__, item['bet_id']))
            logging.warning('pushover_notification_failed bet_id=%s error_type=%s', item['bet_id'], type(error).__name__)
            continue
        with connect() as c:
            c.execute("UPDATE bet_notifications SET status='sent',attempts=attempts+1,sent_at=?,last_error=NULL WHERE bet_id=? AND status='pending'", (now(), item['bet_id']))
        sent += 1
    return sent


def queue_fixture_notification(c, match_id, missing):
    c.execute('INSERT OR IGNORE INTO fixture_notifications(match_id,missing) VALUES(?,?)', (match_id, json.dumps(missing)))


def deliver_pending_fixture_notifications():
    """Deliver one alert per fixture when required pre-bet data missed its cutoff."""
    if not configured():
        return 0
    with connect() as c:
        pending = rows(c, '''SELECT n.match_id,n.missing,h.name home_name,a.name away_name,m.kickoff
          FROM fixture_notifications n JOIN matches m ON m.id=n.match_id
          JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away
          WHERE n.status='pending' ORDER BY m.kickoff,n.match_id''')
    sent = 0
    for item in pending:
        missing = ', '.join(json.loads(item['missing']))
        payload = {'token': os.environ['PUSHOVER_APP_TOKEN'], 'user': os.environ['PUSHOVER_USER_KEY'],
                   'title': 'Touchline bet not placed',
                   'message': f"{item['home_name']} vs {item['away_name']}\nMissing before the 30-minute cutoff: {missing}",
                   'priority': 0}
        if os.environ.get('PUSHOVER_DEVICE'):
            payload['device'] = os.environ['PUSHOVER_DEVICE']
        if os.environ.get('PUSHOVER_DASHBOARD_URL'):
            payload.update(url=os.environ['PUSHOVER_DASHBOARD_URL'], url_title='Open Touchline')
        try:
            response = httpx.post(PUSHOVER_URL, data=payload, timeout=10)
            response.raise_for_status()
        except httpx.HTTPError as error:
            with connect() as c:
                c.execute("UPDATE fixture_notifications SET attempts=attempts+1,last_error=? WHERE match_id=? AND status='pending'", (type(error).__name__, item['match_id']))
            logging.warning('pushover_fixture_notification_failed match_id=%s error_type=%s', item['match_id'], type(error).__name__)
            continue
        with connect() as c:
            c.execute("UPDATE fixture_notifications SET status='sent',attempts=attempts+1,sent_at=?,last_error=NULL WHERE match_id=? AND status='pending'", (now(), item['match_id']))
        sent += 1
    return sent
