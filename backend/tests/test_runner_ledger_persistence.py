"""runner.run persists every order/fill/position snapshot into a LedgerStore
when one is passed, in addition to (not instead of) the in-memory Portfolio
-- Task 6 item 3. Uses the same mongomock_motor fixture pattern as
test_instrument_master.py / test_ledger_store.py.
"""

from datetime import datetime, timedelta, timezone

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

SYMBOL = "TESTLEDGER"
TIMEFRAME = "1d"


class _FirstBarBuyStrategy:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="first-bar-buy", mode="LONGTERM", timeframe=TIMEFRAME,
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
            symbol=SYMBOL, side=Side.BUY, strength=1.0,
            reason_codes=["test"], stop_hint=90.0,
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
        exchange="NSE", tradingsymbol=SYMBOL, name="Test Ledger Co",
        instrument_token=77, exchange_token=77, instrument_type="EQ",
        segment="NSE", lot_size=1, tick_size=0.05,
    )


def _candles(n: int = 3) -> list[PriceCandle]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        PriceCandle(
            symbol=SYMBOL, timestamp=base + timedelta(days=i),
            open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.0 + i, volume=1000.0,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_runner_persists_orders_fills_and_positions_to_ledger():
    instrument = _instrument()
    candles = _candles()
    feed = HistoricalFeed(_FakeProvider(candles), [instrument], candles[0].timestamp, candles[-1].timestamp, TIMEFRAME)
    execution = SimulatedExecutionClient()
    portfolio = Portfolio()
    client = AsyncMongoMockClient()
    ledger = LedgerStore(client["test_db"], user_id="u1")

    await run(
        strategies=[_FirstBarBuyStrategy()], feed=feed, execution=execution,
        portfolio=portfolio, clock=SimClock(), symbol_for_token=feed.symbol_for_token,
        ledger=ledger,
    )

    stored_fills = await ledger.get_fills(symbol=SYMBOL)
    assert len(stored_fills) == 1
    assert stored_fills[0].symbol == SYMBOL

    order_docs = await ledger.orders.find({}).to_list(length=None)
    assert len(order_docs) == 1
    assert order_docs[0]["symbol"] == SYMBOL

    open_positions = await ledger.get_open_positions()
    assert SYMBOL in open_positions
    assert open_positions[SYMBOL].quantity == portfolio.positions[SYMBOL].quantity


@pytest.mark.asyncio
async def test_runner_reports_progress_after_every_bar():
    instrument = _instrument()
    candles = _candles()
    feed = HistoricalFeed(_FakeProvider(candles), [instrument], candles[0].timestamp, candles[-1].timestamp, TIMEFRAME)
    reports = []

    async def on_progress(progress):
        reports.append(progress)

    await run(
        strategies=[_FirstBarBuyStrategy()], feed=feed, execution=SimulatedExecutionClient(),
        portfolio=Portfolio(), clock=SimClock(), symbol_for_token=feed.symbol_for_token,
        on_progress=on_progress,
    )

    assert [r["bars"] for r in reports] == [1, 2, 3]
    assert reports[-1]["signals"] == 1
    assert reports[-1]["orders"] == 1
    assert reports[-1]["last_symbol"] == SYMBOL
    assert reports[-1]["last_bar_at"] == candles[-1].timestamp
