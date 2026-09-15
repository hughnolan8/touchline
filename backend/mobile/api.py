"""Authenticated v1 API. This app deliberately mounts no legacy/manual endpoints."""
import hmac
import json
import logging
import os
import time
from threading import Lock
import psycopg
from starlette.concurrency import run_in_threadpool
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from .strategy import Strategy
from backend.db import connect, rows, now, setting, set_setting
from backend.engine import portfolios, seconds
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

class Reason(BaseModel):
    reason: str
    count: int

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
    strategy: StrategyUpdate
    data_settings: DataSettings

class Summary(BaseModel):
    generated_at: str
    mode: Literal['paper'] = 'paper'
    account: Account
    engine: EngineStatus
    recent: list[Bet]


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


def status(c):
    success = setting(c, 'mobile_last_success')
    strategy = setting(c, 'strategy')
    trained = [r['competition'] for r in rows(c, 'SELECT DISTINCT competition FROM models') if r['competition'] in LEAGUES]
    reference = success or setting(c, 'mobile_initialized')
    state = 'overdue' if reference and seconds(now(), reference) > 900 else 'starting' if not success else 'running'
    failures = c.execute("SELECT 1 FROM mobile_jobs WHERE status='failed' LIMIT 1").fetchone()
    if state == 'running' and (failures or setting(c, 'mobile_last_run', {}).get('errors', 0)):
        state = 'degraded'
    if not strategy['enabled'] and state == 'running':
        state = 'paused'
    daily = setting(c, 'odds_api_daily', {})
    decisions = setting(c, 'mobile_decisions', {}).get('reasons', {})
    return EngineStatus(status=state, last_success=success, last_attempt=setting(c, 'mobile_last_attempt'),
        configured=setting(c, 'mobile_provider_configured', False), daily_credits=daily.get('credits', 0) if daily.get('date') == now()[:10] else 0,
        provider_remaining=setting(c, 'odds_api_quota', {}).get('remaining'), trained_leagues=trained,
        jobs=rows(c, 'SELECT id,kind,status,attempts,message FROM mobile_jobs ORDER BY available_at DESC LIMIT 20'),
        reasons=[Reason(reason=k, count=v) for k, v in decisions.items()], strategy=strategy,
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
    app = FastAPI(title='Touchline Mobile · Paper Simulation', version='1.0.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def private_cache(request, call_next):
        if not await run_in_threadpool(ensure_ready):
            return JSONResponse({'detail': 'Database unavailable. The engine will retry automatically.'},
                                status_code=503, headers={'Cache-Control': 'no-store', 'Retry-After': '60'})
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

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
