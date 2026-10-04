"""/trading/* -- paper-trading control plane and read-only ledger queries.

Every route is scoped to the authenticated user: the ledger collections are
shared, so `LedgerStore` is always constructed with `user.id` and a run can
only be stopped by the account that started it.

`start_background_run`/`stop_background_run` are deliberately factored out
of the HTTP handlers: they own nothing but the asyncio.Task bookkeeping, so
they can be unit-tested directly against a fake feed that would otherwise
run forever, without needing a real Mongo/yfinance round-trip (see
backend/tests/test_trading_router.py). `_RUNS` is what can be *cancelled*;
`RunStore` is what survives a restart and what the UI reads.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import broadcast
from backend.learning.retune import current_params
from backend.learning.adapt import load_rules
from backend.auth.broker_credentials import get_credential_store
from backend.auth.dependency import get_current_user, require_admin
from backend.auth.models import User
from backend.core.models import Venue
from backend.brokers.protocol import BrokerSessionState
from backend.brokers.registry import BROKERS, get_broker_adapter
from backend.configs.settings import settings
from backend.prefs import PrefsStore
from backend.risk.backtest_gate import BacktestGateStore
from backend.risk.kill_switch import KillSwitchStore
from backend.risk.paper_gate import paper_records
from backend.risk.gate_backtest import backtest_for_gate
from backend.components.quant.indian_stocks import ALL_SCAN_STOCKS
from backend.core.clock import SystemClock
from backend.database import db
from backend.data.providers.yfinance_provider import YFinanceProvider
from backend.engine.session import IST
from backend.data.feeds.candle_poll import CandlePollingFeed
from backend.data.feeds.polling_live import PollingLiveFeed
from backend.engine.execution.broker import BrokerExecutionClient
from backend.engine.execution.live_order_store import LiveOrderStore
from backend.engine.execution.routing import RoutingExecutionClient
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.persistence import LedgerStore
from backend.ws.hub import hub
from backend.ws.publish import publisher_for
from backend.engine.portfolio import Portfolio
from backend.engine.runner import run
from backend.runs import RunStore
from backend.instruments.master import InstrumentMaster
from backend.marks import mark_prices
from backend.options.premiums import live_premium_source
from backend.options.resolver import FO_UNDERLYINGS
from backend.strategies.registry import build_default_strategies
from backend.suggestions.sink import SuggestionSink
from backend.suggestions.store import SuggestionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trading", tags=["Trading"])

# run_id -> the background asyncio.Task driving that run's engine loop.
_RUNS: dict[str, asyncio.Task] = {}

_MODE_TIMEFRAME = {"INTRADAY": "5m", "LONGTERM": "1d"}


def get_ledger_store(user: User = Depends(get_current_user)) -> LedgerStore:
    return LedgerStore(db.db, user_id=user.id, on_change=publisher_for(user.id))


def get_run_store() -> RunStore:
    return RunStore(db.db)


# ---------------------------------------------------------------------------
# Background-task plumbing (testable independent of FastAPI/Mongo/yfinance)
# ---------------------------------------------------------------------------

def start_background_run(coro, run_id: Optional[str] = None, runs: Optional[RunStore] = None) -> str:
    """Schedules `coro` as a background asyncio.Task and returns a run_id
    that /trading/stop (or stop_background_run directly) can cancel by.
    Never awaits the coroutine itself -- the whole point is the HTTP
    request returns immediately even though the engine loop runs
    indefinitely against a live feed.

    `runs`, when given, is updated when the task ends on its own (crash or
    natural completion) so a dead run doesn't stay RUNNING in Mongo."""
    run_id = run_id or str(uuid.uuid4())
    task = asyncio.create_task(coro)
    _RUNS[run_id] = task

    def _cleanup(finished: asyncio.Task) -> None:
        _RUNS.pop(run_id, None)
        if runs is None:
            return
        error = None
        if not finished.cancelled():
            exception = finished.exception()
            if exception is not None:
                error = repr(exception)
        coro_ = runs.mark_error(run_id, error) if error else runs.mark_stopped(run_id)
        asyncio.create_task(coro_)

    task.add_done_callback(_cleanup)
    return run_id


async def live_eligible_strategies(strategies, gate: BacktestGateStore):
    """Keeps only strategies whose most recently stored backtest result
    clears the gate (backend/risk/backtest_gate.py). A strategy with no
    stored result, or a failing one, is excluded -- not an error, just not
    live yet."""
    eligible = []
    for strategy in strategies:
        if await gate.live_eligible(strategy.spec.name):
            eligible.append(strategy)
    return eligible


async def build_feed(instruments, mode: str, poll_interval_seconds: float, user_id: str, credentials):
    """Real broker ticks when this user has a connected session that
    supports streaming, polled quotes otherwise.

    Only intraday benefits: a ticker feed aggregates ticks into bars as they
    arrive, which is exactly what a 5-minute strategy wants and pointless for
    a daily one, where a poll of the current quote is both sufficient and
    available without a broker login. Tries the user's connected brokers in
    a fixed order and uses the first that both is ACTIVE and supports
    streaming (Kite and Upstox do; Angel One doesn't yet) -- BROKERS order in the registry, not
    hardcoded here, is what a fourth streaming-capable broker would join.
    """
    if mode == "INTRADAY":
        for broker in BROKERS:
            adapter = await get_broker_adapter(broker, user_id, credentials, db.redis)
            if await adapter.state() != BrokerSessionState.ACTIVE:
                continue
            feed = await adapter.ticker_feed(instruments, timeframe="5m", timeframe_seconds=300.0)
            if feed is not None:
                logger.info("using live %s ticks for %d instrument(s)", broker, len(instruments))
                return feed

    if mode == "INTRADAY":
        # No broker session: real 5-minute candles, late, rather than a daily
        # quote dressed up as a 5-minute bar.
        return CandlePollingFeed(YFinanceProvider(), instruments)
    return PollingLiveFeed(
        YFinanceProvider(), instruments, timeframe=_MODE_TIMEFRAME[mode],
        poll_interval_seconds=poll_interval_seconds,
    )


async def get_active_broker_adapter(user_id: str, credentials):
    """First broker (BROKERS order) with an ACTIVE session for this user, or
    None. Mirrors build_feed's own loop above -- same order, same ACTIVE
    check -- but returns the adapter itself rather than a feed, since live
    order routing needs to place/cancel orders and read positions, not just
    stream ticks."""
    for broker in BROKERS:
        adapter = await get_broker_adapter(broker, user_id, credentials, db.redis)
        if await adapter.state() == BrokerSessionState.ACTIVE:
            return adapter
    return None


async def ai_broker_adapter(user_id: str, credentials, roles: dict):
    """The AI account's adapter if it is logged in, else None
    (backend/brokers/roles.py). Live engine orders go nowhere else."""
    from backend.brokers.roles import RoleUnavailable, adapter_for

    try:
        return await adapter_for(user_id, "ai", credentials, db.redis, roles=roles, get_adapter=get_broker_adapter)
    except RoleUnavailable:
        return None


async def _cancel_local(run_id: str) -> bool:
    task = _RUNS.get(run_id)
    if task is None:
        return False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    _RUNS.pop(run_id, None)
    return True


async def stop_background_run(run_id: str) -> bool:
    if await _cancel_local(run_id):
        return True

    from backend.database import db as _db
    if _db.redis is None:
        return False
    await broadcast.publish(_db.redis, "runs:cancel", {"run_id": run_id})
    return True


async def handle_cancel_broadcast(payload: dict) -> None:
    """The "runs:cancel" handler registered with backend.broadcast.listen
    (wired up in server.py's startup). Fire-and-forget: the caller that
    published this already confirmed via RunStore that the run is genuinely
    ACTIVE, so "no local task with this id" here just means it belongs to a
    different worker (or already finished -- an existing, harmless race)."""
    await _cancel_local(payload.get("run_id", ""))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    """Risk caps are deliberately absent: they come from the caller's stored
    preferences, so a request cannot size itself past the limits the user
    saved. The scheduled scan path already worked this way."""
    mode: Literal["INTRADAY", "LONGTERM"] = "LONGTERM"
    universe: Optional[list[str]] = None  # tradingsymbols; defaults to ALL_SCAN_STOCKS
    poll_interval_seconds: float = 60.0


class StartResponse(BaseModel):
    run_id: str


class StopRequest(BaseModel):
    run_id: str


PROGRESS_EVERY_SECONDS = 2.0


def progress_reporter(user_id: str, run_id: str, runs: RunStore, cycle: int = 0):
    """The runner reports after every bar; a poll cycle over the default
    universe is ~80 bars in a burst, so this saves and publishes at most one
    update every PROGRESS_EVERY_SECONDS rather than one per bar -- plus one
    whenever a full `cycle` of bars completes, so the end of a burst is never
    the update that got throttled away."""
    last_sent = 0.0

    async def report(progress: dict) -> None:
        nonlocal last_sent
        now = time.monotonic()
        cycle_done = cycle > 0 and progress["bars"] % cycle == 0
        if now - last_sent < PROGRESS_EVERY_SECONDS and not cycle_done:
            return
        last_sent = now
        # ISO strings, not datetimes: the Redis broadcast path is plain json.dumps.
        last_bar_at = progress["last_bar_at"]
        progress = {
            **progress,
            "last_bar_at": last_bar_at.isoformat() if last_bar_at else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await runs.set_progress(run_id, progress)
            await hub.publish(user_id, "runs", "progress", {"run_id": run_id, "progress": progress})
        except Exception as exc:  # a progress hiccup must never stop a live run
            logger.warning("run %s progress update failed: %s", run_id, exc)

    return report


async def launch_run(
    user_id: str, mode: str, universe: Optional[list[str]], poll_interval_seconds: float,
    runs: RunStore, origin: str = "manual",
) -> str:
    """Starts one engine run for `user_id` and returns its run_id. Shared by
    POST /trading/start and the daily intraday auto-run
    (backend/engine/autorun.py); `origin` records which one started it.

    Every registered strategy for `mode` runs on paper. The backtest gate
    decides only which of them may route live -- an unproven strategy still
    paper-trades, which is how it earns a track record at all. Routing live
    also needs that record to clear the paper gate (backend/risk/paper_gate.py)."""
    master = InstrumentMaster(db.db)
    symbols = universe or list(ALL_SCAN_STOCKS)
    credentials = get_credential_store()

    # The intraday options strategy trades only with live premiums from the
    # user's broker, and only on the default universe: its F&O large-caps
    # are fed alongside, not added to the equity strategies' universe.
    premium_source = None
    option_symbols: list[str] = []
    if mode == "INTRADAY" and universe is None:
        premium_source = await live_premium_source(db.db, user_id, credentials, db.redis)
        if premium_source is not None:
            option_symbols = [s for s in FO_UNDERLYINGS if s not in symbols]

    instruments, option_instruments = [], []
    for symbol in symbols + option_symbols:
        instrument = await master.get("NSE", symbol)
        if instrument is not None:
            (option_instruments if symbol in option_symbols else instruments).append(instrument)
    if not instruments:
        raise HTTPException(status_code=400, detail="No resolvable instruments in universe")

    symbol_for_token = {i.instrument_token: i.tradingsymbol for i in instruments + option_instruments}
    strategies = [
        s for s in build_default_strategies(
            universe=[i.tradingsymbol for i in instruments], symbol_for_token=symbol_for_token,
            option_universe=[i.tradingsymbol for i in option_instruments],
            params=await current_params(db.db),
        )
        if s.spec.mode == mode
    ]
    instruments += option_instruments
    if not strategies:
        raise HTTPException(status_code=400, detail=f"No strategies registered for mode {mode!r}")
    prefs = await PrefsStore(db.db).get(user_id)
    account_size = prefs["account_size"]
    max_exposure = prefs["max_exposure"]

    eligible = await live_eligible_strategies(strategies, BacktestGateStore(db.db))
    records = await paper_records(db.db, user_id, [s.spec.name for s in eligible], account_size)
    eligible = [s for s in eligible if records[s.spec.name]["passed"]]

    # Engine orders trade only the AI account; without one logged in, every
    # strategy stays on paper.
    active_adapter = (
        await ai_broker_adapter(user_id, credentials, prefs.get("broker_roles") or {})
        # The autopilot's switch and live mode govern everything trading the
        # AI account, so its stop button stops engine live orders too.
        if prefs.get("autopilot_enabled") and prefs.get("autopilot_live") else None
    )
    live_strategy_names = set(prefs["live_strategies"])
    eligible_names = {s.spec.name for s in eligible}

    # A strategy routes live only if ALL of: the user toggled it live, this
    # broker session is ACTIVE, and it cleared both the backtest gate and
    # this user's paper gate above.
    # Anything uncertain (no active session, not toggled, not eligible)
    # falls back to paper -- never the other way around.
    live_by_strategy: dict[str, BrokerExecutionClient] = {}
    if active_adapter is not None:
        live_order_store = LiveOrderStore(db.db)
        for name in live_strategy_names & eligible_names:
            live_by_strategy[name] = BrokerExecutionClient(active_adapter, live_order_store, user_id=user_id)

    run_id = str(uuid.uuid4())
    feed = await build_feed(
        instruments, mode, poll_interval_seconds,
        user_id=user_id, credentials=credentials,
    )
    paper_execution = SimulatedExecutionClient()
    execution = (
        RoutingExecutionClient(paper=paper_execution, live_by_strategy=live_by_strategy)
        if live_by_strategy else paper_execution
    )
    portfolio = Portfolio()
    if active_adapter is not None and live_by_strategy:
        broker_positions = await active_adapter.get_positions()
        # Scope the merge to symbols actually owned by a live-toggled
        # strategy -- same owner_by_symbol construction runner.run() uses
        # (backend/engine/runner.py) -- so a paper-only strategy's tracked
        # position for a symbol the broker happens to also hold (a manual
        # trade, a previous live session's leftover holding) isn't silently
        # overwritten with the broker's real quantity/avg_price.
        live_symbols = {
            symbol for strategy in strategies for symbol in strategy.spec.universe
            if strategy.spec.name in live_by_strategy
        }
        for symbol, position in broker_positions.items():
            if symbol in live_symbols:
                portfolio.positions[symbol] = position
    ledger = LedgerStore(db.db, user_id=user_id, run_id=run_id, on_change=publisher_for(user_id))

    # INTRADAY orders execute themselves; LONGTERM ones stop at a PENDING
    # suggestion and wait for the user to approve or reject them.
    sink = SuggestionSink(SuggestionStore(db.db), user_id=user_id, run_id=run_id)

    coro = run(
        strategies=strategies, feed=feed, execution=execution, portfolio=portfolio,
        clock=SystemClock(), symbol_for_token=symbol_for_token, redis=db.redis,
        account_size=account_size, max_exposure=max_exposure, ledger=ledger,
        order_sink=sink,
        per_trade_cap=prefs["per_trade_cap"], daily_loss_limit=prefs["daily_loss_limit"],
        kill_switch_store=KillSwitchStore(db.db),
        master=master if premium_source is not None else None, premium_source=premium_source,
        on_progress=progress_reporter(user_id, run_id, runs, cycle=len(instruments)),
        learned=await load_rules(db.db, user_id),
    )
    await runs.create(
        run_id=run_id, user_id=user_id, mode=mode,
        universe=[i.tradingsymbol for i in instruments],
        params={
            "mode": mode, "poll_interval_seconds": poll_interval_seconds, "origin": origin,
            "account_size": account_size, "max_exposure": max_exposure,
            "live_strategies": sorted(live_by_strategy),
            "feed": getattr(feed, "source", "live broker ticks"),
        },
    )
    start_background_run(coro, run_id=run_id, runs=runs)
    await hub.publish(user_id, "runs", "started", await runs.get(run_id))
    logger.info(
        "started %s run %s (mode=%s, %d instruments, live=%s)",
        origin, run_id, mode, len(instruments), sorted(live_by_strategy) or "none",
    )
    return run_id


@router.post("/start", response_model=StartResponse)
async def start_trading(
    req: StartRequest,
    user: User = Depends(get_current_user),
    runs: RunStore = Depends(get_run_store),
):
    run_id = await launch_run(user.id, req.mode, req.universe, req.poll_interval_seconds, runs)
    return StartResponse(run_id=run_id)


@router.post("/stop")
async def stop_trading(
    req: StopRequest,
    user: User = Depends(get_current_user),
    runs: RunStore = Depends(get_run_store),
):
    owner = await runs.get(req.run_id)
    if owner is not None and owner["user_id"] != user.id:
        raise HTTPException(status_code=404, detail=f"No running trading run {req.run_id!r}")

    stopped = await stop_background_run(req.run_id)
    if not stopped:
        raise HTTPException(status_code=404, detail=f"No running trading run {req.run_id!r}")
    await runs.mark_stopped(req.run_id)
    await hub.publish(user.id, "runs", "stopped", await runs.get(req.run_id))
    return {"run_id": req.run_id, "stopped": True}


@router.get("/runs")
async def list_runs(
    user: User = Depends(get_current_user),
    runs: RunStore = Depends(get_run_store),
):
    """Replaces the frontend's localStorage run_id bookkeeping: the server
    knows which runs are live for this user, across reloads and devices."""
    return await runs.list_for_user(user.id)


@router.get("/positions")
async def get_positions(venue: Optional[Venue] = None, ledger: LedgerStore = Depends(get_ledger_store)):
    """The stored unrealized_pnl is always 0 -- the engine loop never marks a
    position to market -- so this route marks it here, at read time, with a
    best-effort live quote per symbol."""
    positions = await ledger.get_open_positions(venue=venue)
    quotes = await mark_prices(db.db, positions.keys())
    portfolio = Portfolio()
    portfolio.positions = positions
    portfolio.equity(quotes)
    return {symbol: position.model_dump() for symbol, position in positions.items()}


@router.get("/kill-switch")
async def get_kill_switch(user: User = Depends(get_current_user)):
    """Today's (IST calendar date) daily-loss kill-switch state for this
    user. Never re-arms itself -- a tripped switch stays tripped until
    tomorrow's date rolls over."""
    trading_day = datetime.now(IST).date()
    trip = await KillSwitchStore(db.db).is_tripped(user.id, trading_day)
    if trip is None:
        return {"tripped": False}
    return {
        "tripped": True,
        "reason": trip["reason"],
        "equity": trip["equity"],
        "tripped_at": trip["tripped_at"],
    }


@router.get("/fills")
async def get_fills(
    symbol: Optional[str] = None,
    since: Optional[datetime] = None,
    venue: Optional[Venue] = None,
    ledger: LedgerStore = Depends(get_ledger_store),
):
    fills = await ledger.get_fills(symbol=symbol, since=since, venue=venue)
    return [fill.model_dump(mode="json") for fill in fills]


@router.get("/trades")
async def get_trades(
    status: Optional[Literal["OPEN", "CLOSED"]] = None,
    limit: int = 200,
    venue: Optional[Venue] = None,
    mode: Optional[Literal["INTRADAY", "LONGTERM"]] = None,
    ledger: LedgerStore = Depends(get_ledger_store),
):
    """Round trips, not executions: `status=OPEN` is what the Active tab
    shows, `CLOSED` the Completed one. `venue` picks the paper or live book;
    omitted, both. `mode` narrows to the intraday or long-term engine."""
    return await ledger.get_trades(status=status, limit=limit, venue=venue, mode=mode)


@router.get("/equity")
async def get_equity(venue: Optional[Venue] = None, ledger: LedgerStore = Depends(get_ledger_store)):
    positions = await ledger.get_open_positions(venue=venue)
    portfolio = Portfolio()
    portfolio.positions = positions
    # No live mark-price source wired into this read-only endpoint --
    # Portfolio.equity() falls back to each position's own avg_price when a
    # symbol isn't in mark_prices, so an empty dict here means realized P&L
    # across open positions plus zero unrealized movement, not a crash.
    equity = portfolio.equity({})
    return {"equity": equity}


@router.get("/instruments")
async def search_instruments(q: str, limit: int = 10):
    master = InstrumentMaster(db.db)
    instruments = await master.search(q, limit=limit)
    return [i.model_dump() for i in instruments]


@router.post("/backtests/{strategy_name}", status_code=202)
async def run_gate_backtest(strategy_name: str, admin: User = Depends(require_admin)):
    """Backtests one strategy over the last year and records the result
    into the backtest gate every user's live routing reads -- hence admin
    only. History comes from the admin's own Kite session when connected
    (a year of 5-minute candles); yfinance otherwise, whose ~60 days of
    intraday history cannot clear the gate's one-year window. Runs in the
    background; GET the same path for the result."""
    kite = await get_broker_adapter("kite", admin.id, get_credential_store(), db.redis)
    provider = kite if await kite.state() == BrokerSessionState.ACTIVE else YFinanceProvider()

    async def _run():
        try:
            await backtest_for_gate(db.db, strategy_name, provider, datetime.now(IST))
        except Exception:
            logger.exception("gate backtest of %s failed", strategy_name)

    asyncio.create_task(_run())
    return {"started": strategy_name, "history": "kite" if provider is kite else "yfinance"}


@router.get("/backtests/{strategy_name}")
async def latest_gate_backtest(strategy_name: str, _user: User = Depends(get_current_user)):
    doc = await BacktestGateStore(db.db).latest(strategy_name)
    if doc is None:
        raise HTTPException(status_code=404, detail="No backtest recorded")
    result = {k: v for k, v in doc["result"].items() if k != "trades"}
    return {"strategy": strategy_name, "passed": doc["passed"], "run_at": doc["run_at"], **result}
