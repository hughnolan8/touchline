"""FastAPI app: HTML pages (Jinja + HTMX), admin actions, health, and the scheduler loop."""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from touchline import accumulator, scheduler
from touchline.config import config, setup_logging
from touchline.db import connect, now
from touchline.jobs import modelling, odds
from touchline.leagues import BY_CODE, LEAGUES
from touchline.web import charts, queries

HERE = Path(__file__).parent
UK = ZoneInfo("Europe/London")  # display times; storage is always UTC
log = logging.getLogger(__name__)
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals |= {"leagues": LEAGUES, "league_names": {lg.code: lg.name for lg in LEAGUES}}
templates.env.filters["pct"] = lambda v, d=1: "–" if v is None else f"{v * 100:.{d}f}%"
templates.env.filters["money"] = lambda v: (
    "–" if v is None else f"{'-' if v < 0 else ''}£{abs(v):,.2f}"
)
templates.env.filters["when"] = lambda v: (
    datetime.fromisoformat(v).strftime("%a %d %b %H:%M") if v else "–"
)


async def _loop() -> None:
    while True:
        try:
            await asyncio.to_thread(scheduler.tick)
        except Exception:
            log.exception("tick crashed")
        await asyncio.sleep(config().tick_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    task = asyncio.create_task(_loop()) if config().scheduler else None
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Touchline", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
basic = HTTPBasic(auto_error=False)


def admin(credentials: HTTPBasicCredentials | None = Depends(basic)) -> None:
    """Admin actions need TOUCHLINE_ADMIN_TOKEN as the basic-auth password; off when unset."""
    token = config().admin_token
    if not token:
        raise HTTPException(403, "Admin actions are disabled: set TOUCHLINE_ADMIN_TOKEN")
    if not credentials or not secrets.compare_digest(credentials.password.encode(), token.encode()):
        raise HTTPException(401, "Admin token required", {"WWW-Authenticate": "Basic"})


def _league(request: Request) -> str | None:
    code = request.query_params.get("league") or None
    return code if code in BY_CODE else None


def page(request: Request, name: str, **context):
    context |= {"league": _league(request), "page": name}
    return templates.TemplateResponse(request, f"{name}.html", context)


@app.get("/")
def overview(request: Request):
    with connect() as conn:
        data = queries.overview(conn, _league(request))
    return page(request, "overview", **data, equity=charts.equity_svg(data["account"]["curve"]))


@app.get("/predictions")
def predictions(request: Request):
    with connect() as conn:
        fixtures = queries.predictions(conn, _league(request), now())
    return page(request, "predictions", fixtures=fixtures)


@app.get("/accumulator")
def accumulator_page(request: Request):
    """Builder state lives in the query string: `leg.<match_id>=<selection>`, `stake`, `auto`."""
    params = request.query_params
    try:
        stake = min(max(float(params.get("stake") or 10), 0.0), 100_000.0)
    except ValueError:
        stake = 10.0
    chosen = {k[4:]: v for k, v in params.items() if k.startswith("leg.") and v}
    auto = params.get("auto", "")
    with connect() as conn:
        if auto.isdigit():
            fixtures = queries.predictions(conn, _league(request), now())
            chosen = accumulator.suggest(fixtures, int(auto))
        data = queries.accumulator_builder(conn, _league(request), now(), chosen, stake)
    size = min(max(int(auto), 1), accumulator.MAX_LEGS) if auto.isdigit() else 3
    return page(request, "accumulator", auto=size, max_legs=accumulator.MAX_LEGS, **data)


@app.get("/bets")
def bets(request: Request):
    with connect() as conn:
        return page(request, "bets", bets=queries.bets(conn, _league(request)))


@app.get("/engine")
def engine(request: Request):
    with connect() as conn:
        return page(
            request, "engine", **queries.engine(conn), admin_enabled=bool(config().admin_token)
        )


ACTIONS = {
    "tick": lambda: scheduler.tick(),
    "odds": lambda: odds.refresh_odds([lg.code for lg in LEAGUES], now()),
    "refit": lambda: [modelling.fit_league(lg.code, now()) for lg in LEAGUES],
}


@app.post("/admin/{action}", dependencies=[Depends(admin)])
async def run_action(action: str):
    if action not in ACTIONS:
        raise HTTPException(404)
    try:
        await asyncio.to_thread(ACTIONS[action])
    except Exception as error:
        log.warning("admin %s failed: %s", action, error)
        raise HTTPException(502, f"{action} failed: {type(error).__name__}") from None
    return RedirectResponse("/engine", status_code=303)


@app.get("/health")
def health():
    with connect() as conn:
        last = conn.execute(
            "SELECT finished_at, ok FROM job_runs WHERE job='tick' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {"ok": True, "scheduler": config().scheduler, "last_tick": dict(last) if last else None}
