from datetime import datetime, timedelta, timezone

import httpx

from backend.db import connect, now
from backend.engine import place_required_bet
from backend.mobile import notifications
from backend.providers import add_quote, ingest_match


def _placed_bet():
    kickoff = (datetime.now(timezone.utc) + timedelta(minutes=58)).isoformat()
    with connect() as c:
        match_id = ingest_match(c, 'test', 'notification', 'E0', 'Arsenal', 'Chelsea', kickoff, True, 'scheduled', {})
        for selection, odds in [('home', 2.4), ('draw', 3.4), ('away', 3.2)]:
            add_quote(c, match_id, '1x2', selection, None, '', 'Bet365', odds, now(), now(), 'test', 'https://example.test', True)
        match = dict(c.execute('SELECT m.*,h.name home_name,a.name away_name FROM matches m JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away WHERE m.id=?', (match_id,)).fetchone())
        assert place_required_bet(c, match, {'probabilities': {'home': .6, 'draw': .2, 'away': .2}}, now()) == 'placed'
    return match_id


def test_pushover_notification_is_queued_and_sent(monkeypatch):
    _placed_bet()
    monkeypatch.setenv('PUSHOVER_APP_TOKEN', 'app-token')
    monkeypatch.setenv('PUSHOVER_USER_KEY', 'user-key')
    sent = []

    class Response:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(notifications.httpx, 'post', lambda *args, **kwargs: sent.append((args, kwargs)) or Response())
    assert notifications.deliver_pending_bet_notifications() == 1
    assert sent[0][0] == (notifications.PUSHOVER_URL,)
    assert sent[0][1]['data']['title'] == 'Touchline bet placed'
    assert 'Arsenal vs Chelsea' in sent[0][1]['data']['message']
    with connect() as c:
        notification = c.execute('SELECT status,attempts,sent_at FROM bet_notifications').fetchone()
    assert notification['status'] == 'sent' and notification['attempts'] == 1 and notification['sent_at']


def test_pushover_failure_stays_queued_for_retry(monkeypatch):
    _placed_bet()
    monkeypatch.setenv('PUSHOVER_APP_TOKEN', 'app-token')
    monkeypatch.setenv('PUSHOVER_USER_KEY', 'user-key')
    monkeypatch.setattr(notifications.httpx, 'post', lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError('offline')))
    assert notifications.deliver_pending_bet_notifications() == 0
    with connect() as c:
        notification = c.execute('SELECT status,attempts,last_error FROM bet_notifications').fetchone()
    assert dict(notification) == {'status': 'pending', 'attempts': 1, 'last_error': 'ConnectError'}
