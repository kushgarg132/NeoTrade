"""Wires HistoricalFeed + SimClock + SimulatedExecutionClient + Portfolio
through the shared runner.run() loop, then reports through the existing
(until now referenced nowhere) `BacktestResult` model.
"""

import logging
import time
import uuid
from collections import deque
from datetime import datetime

import pandas as pd

from backend.components.quant.indicators import Indicators
from backend.components.shared.models import BacktestResult
from backend.core.clock import SimClock
from backend.core.models import Order, Side
from backend.data.feeds.historical import HistoricalFeed
from backend.data.protocols import MarketDataProvider
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.metrics import compute_max_drawdown, compute_sharpe_ratio
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import Strategy
from backend.engine.runner import run
from backend.instruments.models import Instrument
from backend.options.backtest import ModelOptions
from backend.suggestions.exits import trail_level

logger = logging.getLogger(__name__)
PROGRESS_EVERY = 20_000  # bars between progress log lines

# Adverse slippage per side on every backtest fill (spread + impact).
BACKTEST_SLIPPAGE_BPS = 10.0


async def run_backtest(
    strategies: list[Strategy],
    provider: MarketDataProvider,
    instruments: list[Instrument],
    start: datetime,
    end: datetime,
    timeframe: str,
    account_size: float = 1_000_000.0,
    max_exposure: float = 1_000_000.0,
    model_options: ModelOptions | None = None,
    per_trade_cap: float | None = None,
    plan=None,
) -> BacktestResult:
    """`model_options` prices option contracts for an options strategy
    (backend/options/backtest.py); without it an option intent never sizes."""
    feed = HistoricalFeed(provider, instruments, start, end, timeframe)
    names = ",".join(s.spec.name for s in strategies)
    began = time.monotonic()
    logger.info("backtest %s: %d instruments, %s..%s, %s", names, len(instruments), start, end, timeframe)
    # Next-bar-open fills: the signal bar is only known once it has closed.
    execution = SimulatedExecutionClient(slippage_bps=BACKTEST_SLIPPAGE_BPS, fill_on_next_open=True)
    portfolio = Portfolio()
    clock = SimClock()

    bar_timestamps: list[datetime] = []
    original_feed_iter = feed.__aiter__

    # Every equity position opened with a stop/target exits when a later
    # bar's low/high crosses it, at that level (the stop first when both
    # cross -- the conservative reading of an OHLC bar). It used to cover
    # long-term buys only, on the close, so intraday stops were never tested.
    # A swing order (context max_hold_days / trail_atr) also exits at the
    # close of the bar that completes its hold, and at a stop that rises to
    # the highest close since entry minus k x the 14-bar ATR, set from the
    # bars before the one tested -- as suggestions/exits.py does live.
    levels: dict[str, dict] = {}
    recent: dict[str, deque] = {}  # each symbol's last 15 bars: the trail's ATR
    original_submit = execution.submit

    async def submit_noting_levels(order: Order) -> str:
        context = order.context or {}
        held = portfolio.positions.get(order.symbol)
        if order.contract is None and context.get("stop") is not None and (held is None or held.quantity == 0):
            levels[order.symbol] = {
                "stop": context["stop"], "target": context.get("target"), "product": order.product,
                "hold": context.get("max_hold_days"), "k": context.get("trail_atr"), "bars": 0, "high": None}
        return await original_submit(order)

    execution.submit = submit_noting_levels  # type: ignore[method-assign]

    async def exit_on_levels(bar) -> None:
        symbol = feed.symbol_for_token.get(bar.instrument_token)
        past = recent.setdefault(symbol, deque(maxlen=15))
        try:
            await exit_at_level(symbol, bar, past)
        finally:
            past.append(bar)

    async def exit_at_level(symbol, bar, past) -> None:
        position = portfolio.positions.get(symbol)
        if symbol not in levels or position is None or position.quantity == 0:
            return
        lv = levels[symbol]
        stop, target = lv["stop"], lv["target"]
        long = position.quantity > 0
        if long and lv["k"]:  # past[-1] is the entry bar on the first bar held
            lv["high"] = max(lv["high"] or past[-1].close, past[-1].close)
            atr = Indicators.atr(*(pd.Series([getattr(b, f) for b in past]) for f in ("high", "low", "close"))).iloc[-1]
            if not pd.isna(atr):  # kept: a widening ATR never lowers it
                lv["stop"] = stop = max(stop, trail_level(lv["high"], float(atr), lv["k"]))
        if long:
            level = stop if bar.low <= stop else (target if target is not None and bar.high >= target else None)
            gapped = bar.open <= stop
        else:
            level = stop if bar.high >= stop else (target if target is not None and bar.low <= target else None)
            gapped = bar.open >= stop
        if level == stop and gapped and lv["hold"]:
            level = bar.open  # a swing position held overnight gets the gap, not its stop
        lv["bars"] += 1
        if level is None and lv["hold"] and lv["bars"] >= lv["hold"]:
            level = bar.close
        if level is None:
            return
        del levels[symbol]
        await execution.fill_now(Order(
            id=str(uuid.uuid4()), symbol=symbol, side=Side.SELL if long else Side.BUY,
            quantity=abs(position.quantity), order_type="MARKET", limit_price=None, product=lv["product"],
        ), level, bar.timestamp)

    async def timestamped_bars():
        # BacktestResult.start_date/end_date report the *actual* span of
        # candles a data provider returned, not the range the caller asked
        # for -- yfinance's 5m interval silently caps at ~60 days of
        # history no matter what `start` is, so trusting `start`/`end`
        # verbatim would let a caller claim a window the backtest never
        # really ran (see docs/ROADMAP.md Phase 4).
        async for bar in original_feed_iter():
            bar_timestamps.append(bar.timestamp)
            if len(bar_timestamps) % PROGRESS_EVERY == 0:
                logger.info("backtest %s: %d bars, at %s, %d fills, %.0fs",
                            names, len(bar_timestamps), bar.timestamp, len(trades), time.monotonic() - began)
            await exit_on_levels(bar)
            if model_options is not None:
                model_options.observe(feed.symbol_for_token[bar.instrument_token], bar)
            yield bar

    trades: list[dict] = []
    # A round trip: from the fill that opens a position to the one that
    # flattens it -- what "a trade" means; fills are not trades.
    open_pnl: dict[str, float] = {}
    round_trips: list[float] = []
    original_fills = execution.fills

    async def recording_fills():
        # Trade-log bookkeeping belongs here, not on Portfolio/ExecutionClient
        # (both shared with paper/live trading). Peeking at `portfolio`
        # right before and right after the fill is yielded works because the
        # runner applies the fill to `portfolio` between one `yield` and the
        # generator's next resumption.
        async for fill in original_fills():
            pre = portfolio.positions.get(fill.symbol)
            pre_realized = pre.realized_pnl if pre else 0.0
            yield fill  # runner calls portfolio.apply(fill) here
            post = portfolio.positions[fill.symbol]
            gross = post.realized_pnl - pre_realized
            open_pnl[fill.symbol] = open_pnl.get(fill.symbol, 0.0) + gross - fill.costs
            if post.quantity == 0:
                round_trips.append(open_pnl.pop(fill.symbol))
            trades.append({
                "order_id": fill.order_id,
                "symbol": fill.symbol,
                "side": fill.side.value,
                "quantity": fill.quantity,
                "price": fill.price,
                "timestamp": fill.timestamp.isoformat(),
                "costs": fill.costs,
                "gross_pnl": gross,
                # Every fill pays charges, the opening one included; the
                # metrics below are all computed on this net figure.
                "net_pnl": gross - fill.costs,
                "realized_pnl": gross - fill.costs,
            })

    execution.fills = recording_fills  # type: ignore[method-assign]

    await run(
        strategies=strategies,
        feed=timestamped_bars(),
        execution=execution,
        portfolio=portfolio,
        clock=clock,
        symbol_for_token=feed.symbol_for_token,
        account_size=account_size,
        max_exposure=max_exposure,
        per_trade_cap=per_trade_cap,
        master=model_options,
        premium_source=model_options,
        plan=plan,
    )

    logger.info("backtest %s: done, %d bars, %d fills, %.0fs", names, len(bar_timestamps), len(trades),
                time.monotonic() - began)
    actual_start = min(bar_timestamps) if bar_timestamps else start
    actual_end = max(bar_timestamps) if bar_timestamps else start

    total_trades = len(round_trips)
    total_pnl = sum(t["realized_pnl"] for t in trades)
    closed_trades = [t for t in trades if t["realized_pnl"] != 0.0]
    win_rate = sum(1 for pnl in round_trips if pnl > 0) / len(round_trips) if round_trips else 0.0
    gross_profit = sum(t["realized_pnl"] for t in closed_trades if t["realized_pnl"] > 0)
    gross_loss = -sum(t["realized_pnl"] for t in closed_trades if t["realized_pnl"] < 0)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

    return BacktestResult(
        symbol=",".join(instrument.tradingsymbol for instrument in instruments),
        start_date=actual_start,
        end_date=actual_end,
        total_trades=total_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_pnl=total_pnl,
        max_drawdown=compute_max_drawdown(trades, account_size),
        sharpe_ratio=compute_sharpe_ratio(trades, account_size),
        trades=trades,
    )
