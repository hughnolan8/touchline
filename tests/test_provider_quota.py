from datetime import datetime, timezone

import httpx
import pytest

from backend.app.provider import MobileOdds, reserve_request
from backend.db import connect, setting
from backend.odds_api import OddsApiError


AT = datetime(2026, 9, 23, 12, tzinfo=timezone.utc).isoformat()


def test_daily_odds_request_cap_resets_at_utc_midnight(monkeypatch):
    monkeypatch.setenv('TOUCHLINE_ODDS_MAX_REQUESTS_PER_UTC_DAY', '5')
    for _ in range(5):
        reserve_request(AT)
    with pytest.raises(OddsApiError, match='daily request limit reached'):
        reserve_request(AT)
    reserve_request('2026-09-24T00:00:00+00:00')
    with connect() as c:
        assert setting(c, 'odds_api_requests:2026-09-23') == 5
        assert setting(c, 'odds_api_requests:2026-09-24') == 1


def test_failed_provider_request_consumes_reserved_quota(monkeypatch):
    monkeypatch.setenv('TOUCHLINE_ODDS_MAX_REQUESTS_PER_UTC_DAY', '5')

    class UnavailableClient:
        def get(self, *_args, **_kwargs):
            raise httpx.ConnectError('unavailable')

        def close(self):
            pass

    odds = MobileOdds()
    odds.client = UnavailableClient()
    with pytest.raises(OddsApiError, match='request failed'):
        odds._get('/events', {}, AT)
    with connect() as c:
        assert setting(c, 'odds_api_requests:2026-09-23') == 1
