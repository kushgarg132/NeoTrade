"""End-to-end: a trivial strategy that BUYs on the very first bar, run
through the real runner.run() loop (via run_backtest) against a fake
MarketDataProvider (never real yfinance/network) and a tiny synthetic
5-bar feed. Confirms the whole wiring -- HistoricalFeed, SimClock,
SimulatedExecutionClient, Portfolio, StrategyContext -- actually moves a
Fill from a Strategy's Intent into the Portfolio and into BacktestResult.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.components.shared.models import PriceCandle
from backend.core.clock import SimClock
from backend.core.models import Intent, Side
from backend.data.feeds.historical import HistoricalFeed
from backend.engine.backtest import BACKTEST_SLIPPAGE_BPS, run_backtest
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import StrategySpec
from backend.engine.runner import run
from backend.instruments.models import Instrument

SYMBOL = "TEST"
TIMEFRAME = "1d"


class _FakeProvider:
    """MarketDataProvider stub -- ignores interval/period, just replays a
    fixed candle list. Never touches the network."""

    def __init__(self, candles: list[PriceCandle]) -> None:
        self._candles = candles

    async def history(self, instrument, interval, period) -> list[PriceCandle]:
        return self._candles

    async def quote(self, instrument) -> dict:
        return {}


class _FirstBarBuyStrategy:
    """Emits exactly one BUY Intent, on the first bar it ever sees."""

    def __init__(self, symbol: str, timeframe: str) -> None:
        self.spec = StrategySpec(
            name="first-bar-buy", mode="LONGTERM", timeframe=timeframe,
            warmup_bars=0, universe=[symbol],
        )
        self._fired = False

    def on_start(self, ctx) -> None:
        pass

    def on_bar(self, ctx, bar) -> None:
        if self._fired:
            return
        self._fired = True
        ctx.submit(Intent(
            symbol=self.spec.universe[0], side=Side.BUY, strength=1.0,
            reason_codes=["first-bar-test"],
            # Task 6's sizer requires a stop_hint to size at all -- 10 below
            # entry gives a clean risk_per_share=10 for the expected-size math.
            stop_hint=90.0,
        ))

    def on_fill(self, ctx, fill) -> None:
        pass


def _instrument() -> Instrument:
    return Instrument(
        exchange="NSE", tradingsymbol=SYMBOL, name="Test Co",
        instrument_token=42, exchange_token=42, instrument_type="EQ",
        segment="NSE", lot_size=1, tick_size=0.05,
    )


def _candles(n: int = 5) -> list[PriceCandle]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        PriceCandle(
            symbol=SYMBOL, timestamp=base + timedelta(days=i),
            open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.0 + i,
            volume=1000.0,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_backtest_result_shows_exactly_one_trade():
    instrument = _instrument()
    candles = _candles()
    provider = _FakeProvider(candles)
    strategy = _FirstBarBuyStrategy(SYMBOL, TIMEFRAME)

    result = await run_backtest(
        strategies=[strategy], provider=provider, instruments=[instrument],
        start=candles[0].timestamp, end=candles[-1].timestamp, timeframe=TIMEFRAME,
    )

    assert result.total_trades == 1
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["symbol"] == SYMBOL
    assert trade["side"] == "BUY"
    # strength=1.0, no cached sentiment (neutral) -> scored.final = 0.85;
    # risk_pct=0.85% of the default 1,000,000 account / risk_per_share=10
    # (entry 100 - stop_hint 90) = 850 whole shares. See runner.size_intents.
    assert trade["quantity"] == 850.0
    # Filled at the first bar's close plus the backtest's adverse slippage.
    assert trade["price"] == pytest.approx(candles[0].close * (1 + BACKTEST_SLIPPAGE_BPS / 10_000))


@pytest.mark.asyncio
async def test_runner_fill_reflects_in_portfolio_position():
    """Same scenario, driven directly through runner.run() so the resulting
    Portfolio object itself can be inspected (run_backtest only returns the
    reporting-level BacktestResult)."""
    instrument = _instrument()
    candles = _candles()
    provider = _FakeProvider(candles)
    strategy = _FirstBarBuyStrategy(SYMBOL, TIMEFRAME)

    feed = HistoricalFeed(provider, [instrument], candles[0].timestamp, candles[-1].timestamp, TIMEFRAME)
    execution = SimulatedExecutionClient()
    portfolio = Portfolio()
    clock = SimClock()

    await run(
        strategies=[strategy], feed=feed, execution=execution, portfolio=portfolio,
        clock=clock, symbol_for_token=feed.symbol_for_token,
    )

    pos = portfolio.positions[SYMBOL]
    assert pos.quantity == 850.0
    assert pos.avg_price == candles[0].close


@pytest.mark.asyncio
async def test_runner_calls_poll_once_on_an_execution_client_that_has_it():
    """Reuses runner.run()'s existing per-bar loop as the status-poll
    cadence for a live ExecutionClient -- no separate background task."""
    instrument = _instrument()
    candles = _candles(n=3)
    provider = _FakeProvider(candles)
    strategy = _FirstBarBuyStrategy(SYMBOL, TIMEFRAME)

    feed = HistoricalFeed(provider, [instrument], candles[0].timestamp, candles[-1].timestamp, TIMEFRAME)

    class _ExecutionWithPoll(SimulatedExecutionClient):
        def __init__(self):
            super().__init__()
            self.poll_once_calls = 0

        async def poll_once(self):
            self.poll_once_calls += 1

    execution = _ExecutionWithPoll()
    portfolio = Portfolio()
    clock = SimClock()

    await run(
        strategies=[strategy], feed=feed, execution=execution, portfolio=portfolio,
        clock=clock, symbol_for_token=feed.symbol_for_token,
    )

    assert execution.poll_once_calls == len(candles)


async def test_slippage_moves_fills_against_the_trader():
    from backend.core.models import Bar, Order

    execution = SimulatedExecutionClient(slippage_bps=10)
    execution.mark(SYMBOL, 100.0, datetime(2024, 1, 1, tzinfo=timezone.utc))
    for side in (Side.BUY, Side.SELL):
        await execution.submit(Order(id=side.value, symbol=SYMBOL, side=side, quantity=1,
                                     order_type="MARKET", limit_price=None, product="CNC"))
    fills = {f.side: f.price for f in [f async for f in execution.fills()]}
    assert fills == {Side.BUY: pytest.approx(100.1), Side.SELL: pytest.approx(99.9)}


async def test_backtest_totals_are_net_of_costs():
    result = await run_backtest(
        strategies=[_FirstBarBuyStrategy(SYMBOL, TIMEFRAME)], provider=_FakeProvider(_candles()),
        instruments=[_instrument()], start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 10, tzinfo=timezone.utc), timeframe=TIMEFRAME,
    )
    # Only an opening buy: nothing realized, but its charges are a real loss.
    assert result.trades and result.trades[0]["costs"] > 0
    assert result.total_pnl == pytest.approx(-sum(t["costs"] for t in result.trades))
    assert result.trades[0]["net_pnl"] == pytest.approx(-result.trades[0]["costs"])
