"""MIS intraday square-off: an INTRADAY-mode strategy's open position must
be force-closed once a bar lands at/past 15:15 IST -- both for a live-style
feed (a hand-rolled async iterator, like PollingLiveFeed's shape) and for a
HistoricalFeed-driven backtest replaying bars across that time of day. Same
runner.run() code path drives both (backend.engine.session.
is_past_square_off_time is keyed off the bar's own timestamp, not wall-clock
time), so both must behave identically.
"""

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest

from backend.core.models import PriceCandle
from backend.core.clock import SimClock
from backend.core.models import Bar, Intent, Side
from backend.data.feeds.historical import HistoricalFeed
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import StrategySpec
from backend.engine.runner import run
from backend.instruments.models import Instrument

SYMBOL = "TESTINTRA"
TOKEN = 99
TIMEFRAME = "5m"

# 09:20 IST == 03:50 UTC; 15:16 IST == 09:46 UTC -- same calendar day, one
# bar before the square-off cutoff, one bar just after it.
BAR1_TS = datetime(2024, 1, 1, 3, 50, tzinfo=timezone.utc)
BAR2_TS = datetime(2024, 1, 1, 9, 46, tzinfo=timezone.utc)
PRICE1 = 100.0
PRICE2 = 105.0
STOP_HINT = 90.0


class _OpenOnFirstBarIntradayStrategy:
    """Emits exactly one BUY intent on the first bar it sees, then stays
    quiet -- an intraday strategy that opened a position and (correctly)
    doesn't try to trade again once the session is winding down."""

    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="open-on-first-bar", mode="INTRADAY", timeframe=TIMEFRAME,
            warmup_bars=0, universe=[SYMBOL],
        )
        self._fired = False

    def on_start(self, ctx) -> None:
        pass

    def on_bar(self, ctx, bar) -> None:
        if self._fired:
            return
        self._fired = True
        ctx.submit(Intent(
            symbol=SYMBOL, side=Side.BUY, strength=0.9,
            reason_codes=["test-open"], stop_hint=STOP_HINT,
        ))

    def on_fill(self, ctx, fill) -> None:
        pass


class _TwoBarLiveFeed:
    """Hand-rolled async iterator, same DataFeed shape PollingLiveFeed
    produces, but with fixed timestamps for a deterministic test."""

    async def __aiter__(self) -> AsyncIterator[Bar]:
        yield Bar(
            instrument_token=TOKEN, timeframe=TIMEFRAME, timestamp=BAR1_TS,
            open=PRICE1, high=PRICE1, low=PRICE1, close=PRICE1, volume=1000.0,
        )
        yield Bar(
            instrument_token=TOKEN, timeframe=TIMEFRAME, timestamp=BAR2_TS,
            open=PRICE2, high=PRICE2, low=PRICE2, close=PRICE2, volume=1000.0,
        )


@pytest.mark.asyncio
async def test_live_style_feed_squares_off_intraday_position_at_1516_ist():
    strategy = _OpenOnFirstBarIntradayStrategy()
    execution = SimulatedExecutionClient()
    portfolio = Portfolio()

    await run(
        strategies=[strategy], feed=_TwoBarLiveFeed(), execution=execution,
        portfolio=portfolio, clock=SimClock(), symbol_for_token={TOKEN: SYMBOL},
    )

    assert SYMBOL in portfolio.positions
    pos = portfolio.positions[SYMBOL]
    assert pos.quantity == 0.0  # squared off, not left open into the close
    assert pos.realized_pnl != 0.0  # proves a real closing fill happened, not just "never opened"


def _instrument() -> Instrument:
    return Instrument(
        exchange="NSE", tradingsymbol=SYMBOL, name="Test Intraday Co",
        instrument_token=TOKEN, exchange_token=TOKEN, instrument_type="EQ",
        segment="NSE", lot_size=1, tick_size=0.05,
    )


class _FakeProvider:
    def __init__(self, candles: list[PriceCandle]) -> None:
        self._candles = candles

    async def history(self, instrument, interval, period) -> list[PriceCandle]:
        return self._candles

    async def quote(self, instrument) -> dict:
        return {}


@pytest.mark.asyncio
async def test_historical_feed_backtest_squares_off_intraday_position_at_1516_ist():
    """Same scenario, but driven through HistoricalFeed -- proves the
    square-off constraint is enforced during backtests too, not just live
    runs, since it's keyed off the bar's own timestamp."""
    instrument = _instrument()
    candles = [
        PriceCandle(symbol=SYMBOL, timestamp=BAR1_TS, open=PRICE1, high=PRICE1, low=PRICE1, close=PRICE1, volume=1000.0),
        PriceCandle(symbol=SYMBOL, timestamp=BAR2_TS, open=PRICE2, high=PRICE2, low=PRICE2, close=PRICE2, volume=1000.0),
    ]
    provider = _FakeProvider(candles)
    feed = HistoricalFeed(provider, [instrument], BAR1_TS, BAR2_TS, TIMEFRAME)
    strategy = _OpenOnFirstBarIntradayStrategy()
    execution = SimulatedExecutionClient()
    portfolio = Portfolio()

    await run(
        strategies=[strategy], feed=feed, execution=execution, portfolio=portfolio,
        clock=SimClock(), symbol_for_token=feed.symbol_for_token,
    )

    assert SYMBOL in portfolio.positions
    pos = portfolio.positions[SYMBOL]
    assert pos.quantity == 0.0
    assert pos.realized_pnl != 0.0
