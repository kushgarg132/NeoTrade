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

from backend.components.quant.indian_stocks import ALL_SCAN_STOCKS
from backend.components.shared.models import BacktestResult
from backend.engine.backtest import run_backtest
from backend.instruments.master import InstrumentMaster
from backend.options.backtest import ModelOptions
from backend.options.resolver import FO_UNDERLYINGS
from backend.risk.backtest_gate import BacktestGateStore
from backend.strategies.registry import build_default_strategies

logger = logging.getLogger(__name__)

OPTIONS_STRATEGIES = {"orb_options"}


async def backtest_for_gate(db, strategy_name: str, provider, now: datetime) -> BacktestResult:
    master = InstrumentMaster(db)
    options = strategy_name in OPTIONS_STRATEGIES
    lot_sizes = {}
    if options:
        for symbol in FO_UNDERLYINGS:
            if contracts := await master.option_contracts(symbol, "CE"):
                lot_sizes[symbol] = contracts[0].lot_size
    symbols = list(lot_sizes) if options else list(ALL_SCAN_STOCKS)

    instruments = [i for s in symbols if (i := await master.get("NSE", s)) is not None]
    if not instruments:
        raise ValueError(
            "No instruments to backtest" + (" (connect Kite to sync NFO lot sizes)" if options else "")
        )
    universe = [i.tradingsymbol for i in instruments]
    symbol_for_token = {i.instrument_token: i.tradingsymbol for i in instruments}
    strategies = [
        s for s in build_default_strategies(
            universe=universe, symbol_for_token=symbol_for_token,
            option_universe=universe if options else None,
        )
        if s.spec.name == strategy_name
    ]
    if not strategies:
        raise ValueError(f"No registered strategy named {strategy_name!r}")

    result = await run_backtest(
        strategies, provider, instruments, start=now - timedelta(days=365), end=now,
        timeframe=strategies[0].spec.timeframe,
        model_options=ModelOptions(lot_sizes) if options else None,
    )
    await BacktestGateStore(db).record(strategy_name, result)
    logger.info(
        "gate backtest %s: %d trades, PF %.2f, DD %.2f, %s..%s",
        strategy_name, result.total_trades, result.profit_factor, result.max_drawdown,
        result.start_date, result.end_date,
    )
    return result
