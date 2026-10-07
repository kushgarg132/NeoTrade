"""Runs one registered strategy through a year's backtest and records the
result into the backtest gate (backend/risk/backtest_gate.py) -- the step
docs/ROADMAP.md Phase 4 left as an uncommitted scratch script, so nothing
in the app could make a strategy live-eligible.

The options strategy is backtested on model premiums
(backend/options/backtest.py), with each underlying's lot size taken from
the synced NFO contracts.
"""

import logging
from datetime import datetime, timedelta

from backend.learning.retune import current_params
from backend.components.quant.indian_stocks import ALL_SCAN_STOCKS
from backend.components.shared.models import BacktestResult
from backend.engine.backtest import run_backtest
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.options.backtest import ModelOptions
from backend.options.resolver import FO_UNDERLYINGS
from backend.risk.backtest_gate import BacktestGateStore
from backend.strategies.registry import build_default_strategies
from backend.datalayer.catalysts import catalyst_map
from backend.datalayer.news_sources import nifty200_sectors

logger = logging.getLogger(__name__)

OPTIONS_STRATEGIES = {"orb_options"}


async def intraday_history(db, redis):
    """(broker name, adapter) serving a year of 5-minute candles, or (None, None):
    the admin's Upstox session (free),
    else Kite (needs Kite Connect's paid historical data). yfinance serves
    only ~60 days of intraday bars, too short for the gate or a re-tune."""
    from backend.auth.broker_credentials import get_credential_store
    from backend.brokers.protocol import BrokerSessionState
    from backend.brokers.registry import get_broker_adapter

    admin = await db["users"].find_one({"role": "admin"}, {"id": 1})
    if admin is None or redis is None:
        return None, None
    for name in ("upstox", "kite"):
        adapter = await get_broker_adapter(name, admin["id"], get_credential_store(), redis)
        if await adapter.state() == BrokerSessionState.ACTIVE:
            return name, adapter
    return None, None


async def backtest_account(db) -> dict:
    """The account the gate and the retune test against: the admin's own
    sizing (the gate is admin-triggered and shared), so backtests size like
    the account that trades -- not an uncapped Rs 10 lakh one. Defaults when
    there is no admin."""
    from backend.prefs import PrefsStore

    admin = await db["users"].find_one({"role": "admin"}, {"id": 1})
    prefs = await PrefsStore(db).get(admin["id"] if admin else "__defaults__")
    return {key: float(prefs[key]) for key in ("account_size", "max_exposure", "per_trade_cap")}


async def gate_universe(db, symbols=ALL_SCAN_STOCKS) -> tuple[list[Instrument], dict[int, str]]:
    """The instruments a gate backtest runs on (the default scan universe) and their token map."""
    master = InstrumentMaster(db)
    instruments = [i for s in symbols if (i := await master.get("NSE", s)) is not None]
    return instruments, {i.instrument_token: i.tradingsymbol for i in instruments}


async def backtest_for_gate(db, strategy_name: str, provider, now: datetime) -> BacktestResult:
    master = InstrumentMaster(db)
    options = strategy_name in OPTIONS_STRATEGIES
    lot_sizes = {}
    if options:
        for symbol in FO_UNDERLYINGS:
            if contracts := await master.option_contracts(symbol, "CE"):
                lot_sizes[symbol] = contracts[0].lot_size
    symbols = list(lot_sizes) if options else list(ALL_SCAN_STOCKS)

    instruments, symbol_for_token = await gate_universe(db, symbols)
    if not instruments:
        raise ValueError(
            "No instruments to backtest" + (" (connect Kite to sync NFO lot sizes)" if options else "")
        )
    universe = [i.tradingsymbol for i in instruments]
    from backend.builder import store
    await store.refresh(db)
    strategies = [
        s for s in build_default_strategies(
            universe=universe, symbol_for_token=symbol_for_token,
            option_universe=universe if options else None,
            regime_of=await store.regime_of(db),
            params=await current_params(db),
            catalysts=await catalyst_map(db, (now - timedelta(days=365)).date(), now.date()),
            sector_of=nifty200_sectors(),
        )
        if s.spec.name == strategy_name
    ]
    if not strategies:
        raise ValueError(f"No registered strategy named {strategy_name!r}")

    result = await run_backtest(
        strategies, provider, instruments, start=now - timedelta(days=365), end=now,
        timeframe=strategies[0].spec.timeframe,
        model_options=ModelOptions(lot_sizes) if options else None,
        **await backtest_account(db),
    )
    await BacktestGateStore(db).record(strategy_name, result)
    logger.info(
        "gate backtest %s: %d trades, PF %.2f, DD %.2f, %s..%s",
        strategy_name, result.total_trades, result.profit_factor, result.max_drawdown,
        result.start_date, result.end_date,
    )
    return result
