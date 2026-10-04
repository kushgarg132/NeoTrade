"""Wires HistoricalFeed + SimClock + SimulatedExecutionClient + Portfolio
through the shared runner.run() loop, then reports through the existing
(until now referenced nowhere) `BacktestResult` model.
"""

import logging
import time
import uuid
from datetime import datetime

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
from backend.suggestions.exits import breach

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
) -> BacktestResult:
    """`model_options` prices option contracts for an options strategy
    (backend/options/backtest.py); without it an option intent never sizes."""
    feed = HistoricalFeed(provider, instruments, start, end, timeframe)
    names = ",".join(s.spec.name for s in strategies)
    began = time.monotonic()
    logger.info("backtest %s: %d instruments, %s..%s, %s", names, len(instruments), start, end, timeframe)
    execution = SimulatedExecutionClient(slippage_bps=BACKTEST_SLIPPAGE_BPS)
    portfolio = Portfolio()
    clock = SimClock()

    bar_timestamps: list[datetime] = []
    original_feed_iter = feed.__aiter__

    # A long-term buy is held until a close crosses its stop or target and
    # is then sold at that close, as paper does (backend/suggestions/exits.py).
    # Without this nothing ever sells it and its P&L never shows.
    levels: dict[str, tuple] = {}
    original_submit = execution.submit

    async def submit_noting_levels(order: Order) -> str:
        context = order.context or {}
        if order.product == "CNC" and order.side == Side.BUY and context.get("stop") is not None:
            levels[order.symbol] = (context["stop"], context.get("target"))
        return await original_submit(order)

    execution.submit = submit_noting_levels  # type: ignore[method-assign]

    async def exit_on_levels(bar) -> None:
        symbol = feed.symbol_for_token.get(bar.instrument_token)
        position = portfolio.positions.get(symbol)
        if symbol not in levels or position is None or position.quantity <= 0:
            return
        if breach(bar.close, *levels[symbol]) is None:
            return
        del levels[symbol]
        execution.mark(symbol, bar.close, bar.timestamp)
        await original_submit(Order(
            id=str(uuid.uuid4()), symbol=symbol, side=Side.SELL, quantity=position.quantity,
            order_type="MARKET", limit_price=None, product="CNC",
        ))

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
        master=model_options,
        premium_source=model_options,
    )

    logger.info("backtest %s: done, %d bars, %d fills, %.0fs", names, len(bar_timestamps), len(trades),
                time.monotonic() - began)
    actual_start = min(bar_timestamps) if bar_timestamps else start
    actual_end = max(bar_timestamps) if bar_timestamps else start

    total_trades = len(trades)
    total_pnl = sum(t["realized_pnl"] for t in trades)
    closed_trades = [t for t in trades if t["realized_pnl"] != 0.0]
    win_rate = (
        sum(1 for t in closed_trades if t["realized_pnl"] > 0) / len(closed_trades)
        if closed_trades
        else 0.0
    )
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
