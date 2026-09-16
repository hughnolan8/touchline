"""Authenticated v1 API. This app deliberately mounts no legacy/manual endpoints."""
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta
from threading import Lock
import psycopg
from starlette.concurrency import run_in_threadpool
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from .strategy import Strategy
from backend.db import connect, rows, now, setting, set_setting
from backend.engine import latest_matches, portfolios, seconds
from .store import configure, initialize, transaction, DATA_DEFAULTS, LEAGUES

logging.getLogger('httpx').setLevel(logging.WARNING)

class StrategyUpdate(Strategy):
    version: int = Field(ge=1)
    model_config = ConfigDict(extra='forbid')

class DataSettings(BaseModel):
    version: int = Field(ge=1)
    auto_refresh: bool = True
    interval_minutes: int = Field(default=15, ge=5, le=60)
    daily_credit_limit: int = Field(default=100, ge=2, le=100000)
    quota_reserve: int = Field(default=10, ge=0, le=10000)
    model_config = ConfigDict(extra='forbid')

class Bet(BaseModel):
    id: int
    home: str
    away: str
    competition: str
    kickoff: str
    created_at: str
    status: str
    stake: float
    profit: float | None
    settled_at: str | None
    reason: str | None
    market: str
    selection: str
    line: float | None
    bookmaker: str
    odds: float
    probability: float
    edge: float
    quote_time: str | None
    strategy_version: int
    stake_mode: str
    bankroll_at_entry: float
    model_id: int

class BetPage(BaseModel):
    items: list[Bet]
    next_cursor: int | None

class Point(BaseModel):
    date: str
    equity: float

class Account(BaseModel):
    balance: float
    available: float
    reserved: float
    profit: float
    roi: float | None
    win_rate: float | None
    settled: int
    open: int
    drawdown: float
    curve: list[Point]

class Job(BaseModel):
    id: str
    kind: str
    status: str
    attempts: int
    message: str | None
    finished_at: str | None

class Reason(BaseModel):
    reason: str
    count: int

class OperationalIssue(BaseModel):
    code: str
    severity: Literal['warning', 'critical']
    title: str
    detail: str

class ComponentHealth(BaseModel):
    name: str
    status: Literal['healthy', 'warning', 'critical', 'unknown']
    detail: str
    last_success: str | None = None

class LeagueReadiness(BaseModel):
    competition: str
    fixtures_status: Literal['fresh', 'stale', 'missing']
    fixtures_at: str | None = None
    odds_status: Literal['fresh', 'stale', 'missing', 'not_configured', 'not_required']
    odds_at: str | None = None
    model_status: Literal['ready', 'missing', 'stale']
    model_at: str | None = None
    model_samples: int | None = None
    forecast_count: int
    blocking_reason: str | None = None

class Operations(BaseModel):
    status: Literal['healthy', 'warning', 'critical']
    last_cycle_outcome: str
    queued_jobs: int
    retrying_jobs: int
    failed_jobs: int
    components: list[ComponentHealth]
    leagues: list[LeagueReadiness]
    issues: list[OperationalIssue]

class EngineStatus(BaseModel):
    status: str
    last_success: str | None
    last_attempt: str | None
    configured: bool
    daily_credits: float
    provider_remaining: float | None
    trained_leagues: list[str]
    jobs: list[Job]
    reasons: list[Reason]
    operations: Operations
    strategy: StrategyUpdate
    data_settings: DataSettings

class Summary(BaseModel):
    generated_at: str
    mode: Literal['paper'] = 'paper'
    account: Account
    engine: EngineStatus
    recent: list[Bet]

class PredictionSelection(BaseModel):
    market: str
    selection: str
    line: float | None
    probability: float
    push: float = 0
    odds: float | None = None
    bookmaker: str | None = None
    quote_time: str | None = None
    implied_probability: float | None = None
    discrepancy: float | None = None

class MatchPrediction(BaseModel):
    id: str
    home: str
    away: str
    competition: str
    kickoff: str
    model_id: int
    created_at: str
    selections: list[PredictionSelection]


def authorize(env_name, authorization):
    expected = os.environ.get(env_name, '')
    if len(expected) < 32:
        raise HTTPException(503, 'Server access token has not been configured')
    provided = authorization.removeprefix('Bearer ') if authorization and authorization.startswith('Bearer ') else ''
    if not hmac.compare_digest(expected.encode(), provided.encode()):
        raise HTTPException(401, 'Invalid access token', headers={'WWW-Authenticate': 'Bearer'})


def owner(authorization: str | None = Header(default=None)):
    authorize('MOBILE_OWNER_TOKEN', authorization)


def serialize_bet(b):
    snap = b['snapshot'] if isinstance(b['snapshot'], dict) else json.loads(b['snapshot'])
    sizing = snap.get('staking', {})
    return Bet(id=b['id'], home=b['home_name'], away=b['away_name'], competition=b['competition'],
               kickoff=b['kickoff'], created_at=b['created_at'], status=b['status'], stake=b['stake'],
               profit=b['profit'], settled_at=b['settled_at'], reason=b['reason'], market=snap['market'],
               selection=snap['selection'], line=snap.get('line'), bookmaker=snap['bookmaker'], odds=snap['odds'],
               probability=snap['probability'], edge=snap['edge'], quote_time=snap.get('quoted_at'),
               strategy_version=snap['strategy']['version'], stake_mode=sizing.get('mode', 'flat'),
               bankroll_at_entry=sizing.get('bankroll', 1000), model_id=snap['model_id'])


def _freshness(at, threshold_seconds):
    if not at:
        return 'missing'
    return 'fresh' if 0 <= seconds(now(), at) <= threshold_seconds else 'stale'


def operations(c, configured, success):
    """A user-safe readiness view. A heartbeat alone is not operational readiness."""
    all_jobs = rows(c, "SELECT id,kind,status,attempts,message,available_at,finished_at FROM mobile_jobs")
    queued = [job for job in all_jobs if job['status'] == 'queued']
    retrying = [job for job in queued if job['attempts'] > 0]
    failed = [job for job in all_jobs if job['status'] == 'failed' and job['kind'] != 'understat']
    issues = []
    last_run = setting(c, 'mobile_last_run', {})
    if not success:
        issues.append(OperationalIssue(code='engine_not_completed', severity='critical', title='Engine has not completed a cycle', detail='The scheduler has not recorded a successful regular cycle yet.'))
    elif seconds(now(), success) > 900:
        issues.append(OperationalIssue(code='engine_overdue', severity='critical', title='Engine heartbeat is overdue', detail='No regular engine cycle has completed in the last 15 minutes.'))
    if retrying:
        issues.append(OperationalIssue(code='jobs_retrying', severity='warning', title='Jobs are retrying', detail=f'{len(retrying)} job(s) will retry automatically; inspect the job list for the next attempt.'))
    if failed:
        issues.append(OperationalIssue(code='jobs_failed', severity='critical', title='Jobs need attention', detail=f'{len(failed)} essential job(s) exhausted automatic retries.'))
    if last_run.get('errors', 0):
        issues.append(OperationalIssue(code='last_cycle_errors', severity='warning', title='Latest cycle had errors', detail='The engine completed, but one or more jobs did not succeed.'))
    if not configured:
        issues.append(OperationalIssue(code='odds_not_configured', severity='warning', title='Odds collection is not configured', detail='Add the Odds API key before the engine can collect current prices.'))

    components = [
        ComponentHealth(name='Engine worker', status='healthy' if success and 0 <= seconds(now(), success) <= 900 else 'critical',
                        detail='Last regular cycle completed.' if success else 'No successful regular cycle recorded.', last_success=success),
        ComponentHealth(name='Job queue', status='critical' if failed else 'warning' if retrying else 'healthy',
                        detail=f'{len(queued)} queued, {len(retrying)} retrying, {len(failed)} failed.'),
        ComponentHealth(name='Odds provider', status='healthy' if configured else 'warning',
                        detail='Current-price collection is configured.' if configured else 'No provider key is configured.'),
    ]
    leagues = []
    for competition in LEAGUES:
        fixture = c.execute('SELECT MAX(observed_at) at FROM matches WHERE competition=?', (competition,)).fetchone()['at']
        quote = c.execute('SELECT MAX(quoted_at) at FROM quotes q JOIN matches m ON m.id=q.match_id WHERE m.competition=? AND q.verified=1', (competition,)).fetchone()['at']
        model = c.execute('SELECT created_at,samples FROM models WHERE competition=? ORDER BY id DESC LIMIT 1', (competition,)).fetchone()
        forecasts = c.execute("SELECT COUNT(*) count FROM predictions p JOIN matches m ON m.id=p.match_id WHERE m.competition=? AND m.status='scheduled' AND m.kickoff>?", (competition, now())).fetchone()['count']
        fixtures_status = _freshness(fixture, 36 * 3600)
        strategy = setting(c, 'strategy')
        current = datetime.fromisoformat(now())
        next_window = (current + timedelta(minutes=strategy['window_end'])).isoformat()
        end_window = (current + timedelta(minutes=strategy['window_start'])).isoformat()
        actionable = c.execute('''SELECT 1 FROM matches WHERE competition=? AND status='scheduled'
            AND time_confirmed=1 AND kickoff>=? AND kickoff<=? LIMIT 1''', (competition, next_window, end_window)).fetchone()
        odds_status = 'not_configured' if not configured else _freshness(quote, 30 * 60) if actionable else 'not_required'
        model_at = model['created_at'] if model else None
        model_status = 'missing' if not model else 'ready' if _freshness(model_at, 14 * 86400) == 'fresh' else 'stale'
        blockers = []
        if fixtures_status != 'fresh': blockers.append('fixtures are not fresh')
        if odds_status not in ('fresh', 'not_configured', 'not_required'): blockers.append('prices are not fresh')
        if odds_status == 'not_configured': blockers.append('odds collection is not configured')
        if model_status != 'ready': blockers.append('model is ' + model_status)
        leagues.append(LeagueReadiness(competition=competition, fixtures_status=fixtures_status, fixtures_at=fixture,
                        odds_status=odds_status, odds_at=quote, model_status=model_status, model_at=model_at,
                        model_samples=model['samples'] if model else None, forecast_count=forecasts,
                        blocking_reason='; '.join(blockers) if blockers else None))
    severity = 'critical' if any(issue.severity == 'critical' for issue in issues) else 'warning' if issues else 'healthy'
    outcome = 'completed_with_errors' if last_run.get('errors', 0) else 'completed_no_work_due' if last_run.get('jobs') == 0 else 'completed_with_work'
    return Operations(status=severity, last_cycle_outcome=outcome, queued_jobs=len(queued), retrying_jobs=len(retrying),
                      failed_jobs=len(failed), components=components, leagues=leagues, issues=issues)


def status(c):
    success = setting(c, 'mobile_last_success')
    strategy = setting(c, 'strategy')
    trained = [r['competition'] for r in rows(c, 'SELECT DISTINCT competition FROM models') if r['competition'] in LEAGUES]
    reference = success or setting(c, 'mobile_initialized')
    state = 'overdue' if reference and seconds(now(), reference) > 900 else 'starting' if not success else 'running'
    # Optional research feeds enrich the model when available, but must not
    # make the live paper ledger look unhealthy when a third-party archive is
    # temporarily unavailable.
    failures = c.execute("SELECT 1 FROM mobile_jobs WHERE status='failed' AND kind != 'understat' LIMIT 1").fetchone()
    if state == 'running' and (failures or setting(c, 'mobile_last_run', {}).get('errors', 0)):
        state = 'degraded'
    if not strategy['enabled'] and state == 'running':
        state = 'paused'
    daily = setting(c, 'odds_api_daily', {})
    decisions = setting(c, 'mobile_decisions', {}).get('reasons', {})
    return EngineStatus(status=state, last_success=success, last_attempt=setting(c, 'mobile_last_attempt'),
        configured=setting(c, 'mobile_provider_configured', False), daily_credits=daily.get('credits', 0) if daily.get('date') == now()[:10] else 0,
        provider_remaining=setting(c, 'odds_api_quota', {}).get('remaining'), trained_leagues=trained,
        jobs=rows(c, "SELECT id,kind,status,attempts,message,finished_at FROM mobile_jobs ORDER BY CASE WHEN status='failed' THEN 0 WHEN status='queued' AND attempts>0 THEN 1 ELSE 2 END, COALESCE(finished_at, available_at) DESC LIMIT 20"),
        reasons=[Reason(reason=k, count=v) for k, v in decisions.items()], strategy=strategy,
        operations=operations(c, setting(c, 'mobile_provider_configured', False), success),
        data_settings={**DATA_DEFAULTS, **setting(c, 'odds_api_config', {})})


def create_app(setup=True):
    initialization_lock = Lock()
    retry_after = 0.0

    def ensure_ready():
        nonlocal retry_after
        with initialization_lock:
            if getattr(app.state, 'initialized', False):
                return True
            if time.monotonic() < retry_after:
                return False
            try:
                initialize()
                app.state.initialized = True
                return True
            except psycopg.OperationalError:
                # A quota outage must not crash ASGI startup or disclose connection details.
                retry_after = time.monotonic() + 60
                logging.error('Mobile database unavailable; initialization will retry in 60 seconds')
                return False

    @asynccontextmanager
    async def lifespan(app):
        if setup:
            configure()
        await run_in_threadpool(ensure_ready)
        yield
    app = FastAPI(title='Touchline · Paper Simulation', version='1.0.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    web_root = Path(__file__).resolve().parents[2] / 'web'
    app.mount('/static', StaticFiles(directory=web_root / 'static'), name='static')

    @app.middleware('http')
    async def private_cache(request, call_next):
        if request.url.path == '/' or request.url.path.startswith('/static/'):
            return await call_next(request)
        if not await run_in_threadpool(ensure_ready):
            return JSONResponse({'detail': 'Database unavailable. The engine will retry automatically.'},
                                status_code=503, headers={'Cache-Control': 'no-store', 'Retry-After': '60'})
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/', include_in_schema=False)
    def dashboard():
        return FileResponse(web_root / 'index.html', headers={'Cache-Control': 'no-store'})

    @app.exception_handler(psycopg.OperationalError)
    async def database_unavailable(request, exc):
        nonlocal retry_after
        app.state.initialized = False
        retry_after = time.monotonic() + 60
        logging.error('Mobile database connection unavailable')
        return JSONResponse({'detail': 'Database unavailable. The engine will retry automatically.'},
                            status_code=503, headers={'Retry-After': '60', 'Cache-Control': 'no-store'})

    @app.get('/health')
    def health():
        with connect() as c:
            c.execute('SELECT 1').fetchone()
        return {'ok': True, 'service': 'touchline-mobile', 'mode': 'paper'}

    @app.get('/health/engine')
    def engine_health():
        with connect() as c:
            last = setting(c, 'mobile_last_success')
            healthy = bool(last and 0 <= seconds(now(), last) <= 900)
        return JSONResponse({'ok': healthy}, status_code=200 if healthy else 503)

    @app.get('/api/v1/summary', response_model=Summary, dependencies=[Depends(owner)])
    def summary():
        with connect() as c:
            account = portfolios(c)[0]
            return Summary(generated_at=now(), account=account, engine=status(c),
                           recent=[serialize_bet(b) for b in account['bets'][:5]])

    @app.get('/api/v1/performance', response_model=Account, dependencies=[Depends(owner)])
    def performance():
        with connect() as c:
            return portfolios(c)[0]

    @app.get('/api/v1/predictions', response_model=list[MatchPrediction], dependencies=[Depends(owner)])
    def predictions():
        with connect() as c:
            matches = [match for match in latest_matches(c) if match['status'] == 'scheduled' and match['kickoff'] > now() and match['prediction']]
            match_ids = [match['id'] for match in matches]
            latest_quotes = []
            if match_ids:
                placeholders = ','.join('?' for _ in match_ids)
                latest_quotes = rows(c, f'''SELECT q.* FROM quotes q WHERE q.id IN (
                    SELECT MAX(id) FROM quotes WHERE match_id IN ({placeholders})
                    GROUP BY match_id,market,selection,line,player,rules,bookmaker)''', match_ids)
            best_quotes = {}
            for quote in latest_quotes:
                if not quote['verified'] or not quote['quoted_at']:
                    continue
                key = (quote['match_id'], quote['market'], quote['selection'], quote['line'], quote['player'])
                if key not in best_quotes or quote['odds'] > best_quotes[key]['odds']:
                    best_quotes[key] = quote
            forecasts = []
            for match in matches:
                selections = []
                for selection in match['prediction'].get('selections', []):
                    quote = best_quotes.get((match['id'], selection['market'], selection['selection'], selection.get('line'), selection.get('player', '')))
                    odds = quote['odds'] if quote else None
                    implied_probability = 1 / odds if odds else None
                    selections.append(PredictionSelection(**selection, odds=odds,
                                                        bookmaker=quote['bookmaker'] if quote else None,
                                                        quote_time=quote['quoted_at'] if quote else None,
                                                        implied_probability=implied_probability,
                                                        discrepancy=selection['probability'] - implied_probability if implied_probability else None))
                forecasts.append(MatchPrediction(
                    id=match['id'], home=match['home_name'], away=match['away_name'],
                    competition=match['competition'], kickoff=match['kickoff'], model_id=match['model_id'],
                    created_at=match['prediction_at'], selections=selections))
            return forecasts

    @app.get('/api/v1/engine', response_model=EngineStatus, dependencies=[Depends(owner)])
    def engine():
        with connect() as c:
            return status(c)

    @app.get('/api/v1/bets', response_model=BetPage, dependencies=[Depends(owner)])
    def bets(cursor: int | None = Query(default=None, ge=1), limit: int = Query(default=30, ge=1, le=100),
             state: Literal['all', 'open', 'settled'] = 'all'):
        with connect() as c:
            filters = "b.portfolio='automatic'"
            params = []
            if cursor:
                filters += ' AND b.id<?'
                params.append(cursor)
            if state == 'open':
                filters += " AND b.status IN ('open','review')"
            elif state == 'settled':
                filters += " AND b.status NOT IN ('open','review')"
            found = rows(c, f'''SELECT b.*,h.name home_name,a.name away_name,m.competition,m.kickoff FROM bets b
              JOIN matches m ON m.id=b.match_id JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away
              WHERE {filters} ORDER BY b.id DESC LIMIT ?''', (*params, limit + 1))
            return BetPage(items=[serialize_bet(b) for b in found[:limit]], next_cursor=found[limit-1]['id'] if len(found)>limit else None)

    @app.get('/api/v1/bets/{bet_id}', response_model=Bet, dependencies=[Depends(owner)])
    def bet(bet_id: int):
        with connect() as c:
            found = c.execute('''SELECT b.*,h.name home_name,a.name away_name,m.competition,m.kickoff FROM bets b
              JOIN matches m ON m.id=b.match_id JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away
              WHERE b.id=? AND b.portfolio='automatic' ''', (bet_id,)).fetchone()
            if not found:
                raise HTTPException(404, 'Simulation not found')
            return serialize_bet(dict(found))

    def save(key, value):
        with transaction() as c:
            current = setting(c, key)
            if value.version != current['version']:
                raise HTTPException(409, 'Settings changed. Refresh and try again.')
            updated = {**value.model_dump(), 'version': value.version + 1}
            set_setting(c, key, updated)
        return updated

    @app.put('/api/v1/strategy', response_model=StrategyUpdate, dependencies=[Depends(owner)])
    def strategy(body: StrategyUpdate):
        return save('strategy', body)

    @app.put('/api/v1/data-settings', response_model=DataSettings, dependencies=[Depends(owner)])
    def data_settings(body: DataSettings):
        return save('odds_api_config', body)

    return app
