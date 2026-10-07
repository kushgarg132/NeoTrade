"""runner.run wires the daily loss kill-switch: once a run's cumulative
realized+unrealized P&L breaches the configured limit, no further INTRADAY
order is submitted for the rest of the run, and the trip is persisted so a
restarted run the same day stays blocked too.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.components.shared.models import PriceCandle
from backend.core.clock import SimClock
from backend.core.models import Intent, Side
from backend.data.feeds.historical import HistoricalFeed
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.persistence import LedgerStore
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import StrategySpec
from backend.engine.runner import run
from backend.instruments.models import Instrument
from backend.risk.kill_switch import KillSwitchStore

SYMBOL = "TESTKS"
TIMEFRAME = "1d"


class _BuyEveryBarStrategy:
    """Fires an INTRADAY buy on every bar it sees -- simplest way to prove
    the kill-switch actually suppresses a second attempt, not just the
    first bar's coincidental outcome."""

    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="buy-every-bar", mode="INTRADAY", timeframe=TIMEFRAME,
            warmup_bars=0, universe=[SYMBOL],
        )

    def on_start(self, ctx) -> None:
        pass

    def on_bar(self, ctx, bar) -> None:
        ctx.submit(Intent(
            symbol=SYMBOL, side=Side.BUY, strength=1.0,
            reason_codes=["test"], stop_hint=bar.close - 50.0,  # wide stop -> real size
        ))

    def on_fill(self, ctx, fill) -> None:
        pass


class _FakeProvider:
    def __init__(self, candles: list[PriceCandle]) -> None:
        self._candles = candles

    async def history(self, instrument, interval, period) -> list[PriceCandle]:
        return self._candles

    async def quote(self, instrument) -> dict:
        return {}


def _instrument() -> Instrument:
    return Instrument(
        exchange="NSE", tradingsymbol=SYMBOL, name="Test KS Co", instrument_token=88,
        exchange_token=88, instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )


def _candles(closes: list[float]) -> list[PriceCandle]:
    base = datetime(2026, 9, 10, tzinfo=timezone.utc)
    return [
        PriceCandle(
            symbol=SYMBOL, timestamp=base + timedelta(days=i),
            open=c, high=c + 1, low=c - 1, close=c, volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


@pytest.mark.asyncio
async def test_a_breach_blocks_further_intraday_orders_the_same_run():
    # bar0 buys at 100; bar1 crashes to 40 -- a large unrealized loss on the
    # position bought at bar0 -- which must block the bar1 buy attempt too.
    instrument = _instrument()
    candles = _candles([100.0, 40.0, 40.0])
    feed = HistoricalFeed(
        _FakeProvider(candles), [instrument], candles[0].timestamp, candles[-1].timestamp, TIMEFRAME,
    )
    execution = SimulatedExecutionClient()
    portfolio = Portfolio()
    client = AsyncMongoMockClient()
    ledger = LedgerStore(client["test_db"], user_id="alice")
    kill_switch = KillSwitchStore(client["test_db"])

    await run(
        strategies=[_BuyEveryBarStrategy()], feed=feed, execution=execution,
        portfolio=portfolio, clock=SimClock(), symbol_for_token=feed.symbol_for_token,
        ledger=ledger, daily_loss_limit=5_000.0, kill_switch_store=kill_switch,
    )

    fills = await ledger.get_fills(symbol=SYMBOL)
    assert len(fills) == 1  # only the bar0 fill -- bar1's and bar2's attempts were blocked

    trip = await kill_switch.is_tripped("alice", date(2026, 9, 11))
    assert trip is not None


@pytest.mark.asyncio
async def test_no_daily_loss_limit_means_the_kill_switch_never_engages():
    instrument = _instrument()
    candles = _candles([100.0, 40.0])
    feed = HistoricalFeed(
        _FakeProvider(candles), [instrument], candles[0].timestamp, candles[-1].timestamp, TIMEFRAME,
    )
    execution = SimulatedExecutionClient()
    portfolio = Portfolio()
    client = AsyncMongoMockClient()
    ledger = LedgerStore(client["test_db"], user_id="alice")

    await run(
        strategies=[_BuyEveryBarStrategy()], feed=feed, execution=execution,
        portfolio=portfolio, clock=SimClock(), symbol_for_token=feed.symbol_for_token,
        ledger=ledger,  # daily_loss_limit omitted
    )

    fills = await ledger.get_fills(symbol=SYMBOL)
    assert len(fills) == 2  # both bars traded -- nothing blocked


@pytest.mark.asyncio
async def test_a_run_already_tripped_today_starts_blocked():
    """A restarted run must not get a fresh chance to lose more before it
    re-detects the breach -- the persisted trip blocks it from bar zero."""
    instrument = _instrument()
    candles = _candles([100.0])
    feed = HistoricalFeed(
        _FakeProvider(candles), [instrument], candles[0].timestamp, candles[-1].timestamp, TIMEFRAME,
    )
    execution = SimulatedExecutionClient()
    portfolio = Portfolio()
    client = AsyncMongoMockClient()
    ledger = LedgerStore(client["test_db"], user_id="alice")
    kill_switch = KillSwitchStore(client["test_db"])
    await kill_switch.trip("alice", date(2026, 9, 10), reason="earlier run breached it", equity=-9000.0)

    await run(
        strategies=[_BuyEveryBarStrategy()], feed=feed, execution=execution,
        portfolio=portfolio, clock=SimClock(), symbol_for_token=feed.symbol_for_token,
        ledger=ledger, daily_loss_limit=5_000.0, kill_switch_store=kill_switch,
    )

    fills = await ledger.get_fills(symbol=SYMBOL)
    assert fills == []


@pytest.mark.asyncio
async def test_a_zero_limit_is_off_not_a_trip_at_once():
    # Settings > Safety: 0 turns the daily loss limit and the kill switch off.
    instrument = _instrument()
    candles = _candles([100.0, 40.0])
    feed = HistoricalFeed(
        _FakeProvider(candles), [instrument], candles[0].timestamp, candles[-1].timestamp, TIMEFRAME,
    )
    client = AsyncMongoMockClient()
    ledger = LedgerStore(client["test_db"], user_id="alice")
    kill_switch = KillSwitchStore(client["test_db"])

    await run(
        strategies=[_BuyEveryBarStrategy()], feed=feed, execution=SimulatedExecutionClient(),
        portfolio=Portfolio(), clock=SimClock(), symbol_for_token=feed.symbol_for_token,
        ledger=ledger, daily_loss_limit=0.0, kill_switch_store=kill_switch,
    )

    assert len(await ledger.get_fills(symbol=SYMBOL)) == 2
    assert await kill_switch.is_tripped("alice", date(2026, 9, 10)) is None


@pytest.mark.asyncio
async def test_losses_booked_by_an_earlier_run_today_count_toward_the_limit():
    # A restarted run starts with an empty portfolio; the day's realized loss
    # from the run before it must still count, or every restart re-arms it.
    instrument = _instrument()
    candles = _candles([100.0, 100.0])
    feed = HistoricalFeed(
        _FakeProvider(candles), [instrument], candles[0].timestamp, candles[-1].timestamp, TIMEFRAME,
    )
    client = AsyncMongoMockClient()
    ledger = LedgerStore(client["test_db"], user_id="alice")
    kill_switch = KillSwitchStore(client["test_db"])

    await run(
        strategies=[_BuyEveryBarStrategy()], feed=feed, execution=SimulatedExecutionClient(),
        portfolio=Portfolio(), clock=SimClock(), symbol_for_token=feed.symbol_for_token,
        ledger=ledger, daily_loss_limit=5_000.0, kill_switch_store=kill_switch, day_realized=-6_000.0,
    )

    assert await ledger.get_fills(symbol=SYMBOL) == []
    assert await kill_switch.is_tripped("alice", date(2026, 9, 10)) is not None
