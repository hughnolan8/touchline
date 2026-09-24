import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path


spec = importlib.util.spec_from_file_location('production_check', Path(__file__).parents[1] / 'scripts/check-production.py')
production_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production_check)


START = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)


def responder(summary=None, api=(200, {'ok': True}), engine=(200, {'ok': True}), errors=None):
    if summary is None:
        summary = {'mode': 'paper', 'engine': {'status': 'running', 'last_success': (START + timedelta(seconds=1)).isoformat(), 'configured': True}}
    responses = {'/health': api, '/health/engine': engine, '/api/v1/summary': (200, summary)}
    errors = errors or {}
    def request(url):
        path = url.removeprefix('https://touchline.test')
        if path in errors:
            return None, None, errors[path]
        status, body = responses[path]
        return status, body, None
    return request


def test_check_accepts_healthy_public_services_after_a_fresh_engine_cycle():
    results, problems, last_success = production_check.check('https://touchline.test', START, responder())
    assert problems == []
    assert results['summary']['status'] == 200
    assert last_success > START


def test_check_rejects_an_unhealthy_engine_endpoint():
    _, problems, _ = production_check.check('https://touchline.test', START, responder(engine=(503, {'ok': False})))
    assert 'Engine health check is unhealthy' in problems


def test_check_rejects_a_missing_odds_key_in_either_process():
    summary = {'mode': 'paper', 'engine': {'status': 'running', 'last_success': (START + timedelta(seconds=1)).isoformat(), 'configured': False}}
    _, problems, _ = production_check.check('https://touchline.test', START, responder(summary=summary))
    assert 'Odds API key is not configured in every process' in problems


def test_check_rejects_malformed_summary_response():
    _, problems, _ = production_check.check('https://touchline.test', START, responder(summary=[]))
    assert 'Summary is unavailable or not in paper mode' in problems
    assert 'Engine summary status is not running' in problems


def test_monitor_times_out_when_the_engine_success_does_not_advance():
    request = responder(summary={'mode': 'paper', 'engine': {'status': 'running', 'last_success': START.isoformat(), 'configured': True}})
    ticks = iter((0, 0, 1, 1))
    ok, _, problems, _ = production_check.monitor('https://touchline.test', 1, 1, request, clock=lambda: START, wait=lambda _: None, timer=lambda: next(ticks))
    assert ok is False
    assert problems == ['Engine has not completed a fresh cycle']


def test_check_reports_unavailable_endpoints_without_response_details():
    _, problems, _ = production_check.check('https://touchline.test', START, responder(errors={'/health': 'unavailable'}))
    assert 'API health check is unhealthy' in problems
