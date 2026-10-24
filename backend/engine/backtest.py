"""Wires HistoricalFeed + SimClock + SimulatedExecutionClient + Portfolio
through the shared runner.run() loop, then reports through the existing
(until now referenced nowhere) `BacktestResult` model.
"""

import logging
import time
from datetime import datetime

from backend.core.models import BacktestResult
from backend.core.clock import SimClock
from backend.data.feeds.historical import HistoricalFeed
from backend.data.protocols import MarketDataProvider
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.metrics import compute_max_drawdown, compute_sharpe_ratio
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import Strategy
from backend.engine.runner import run
from backend.instruments.models import Instrument
from backend.lab.assumptions import DEFAULT
from backend.options.backtest import ModelOptions

logger = logging.getLogger(__name__)
PROGRESS_EVERY = 20_000  # bars between progress log lines

# Kept as a name for callers/tests; the value lives in lab.assumptions.
BACKTEST_SLIPPAGE_BPS: float = DEFAULT.slippage_bps


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
    execution = SimulatedExecutionClient(slippage_bps=DEFAULT.slippage_bps, fill_on_next_open=True)
    portfolio = Portfolio()
    clock = SimClock()

    bar_timestamps: list[datetime] = []
    original_feed_iter = feed.__aiter__

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
    win_rate = sum(1 for pnl in round_trips if pnl > 0) / len(round_trips) if round_trips else 0.0
    # Over round trips, net of both legs' charges, as the paper gate counts
    # them: per fill, every winner's entry charges were booked as a loss.
    gross_profit = sum(pnl for pnl in round_trips if pnl > 0)
    gross_loss = -sum(pnl for pnl in round_trips if pnl < 0)
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
