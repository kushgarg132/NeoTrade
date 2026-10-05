"""runner.run never trades on a warm-up bar: a restarted run's catch-up
candles feed the strategies but place no order at an hours-old price."""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.clock import SimClock
from backend.core.models import Bar
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.persistence import LedgerStore
from backend.engine.portfolio import Portfolio
from backend.engine.runner import run
from backend.tests.test_runner_kill_switch import SYMBOL, TIMEFRAME, _BuyEveryBarStrategy


class _ListFeed:
    symbol_for_token = {88: SYMBOL}

    def __init__(self, bars):
        self._bars = bars

    async def __aiter__(self):
        for bar in self._bars:
            yield bar


def _bar(i, close, warmup):
    return Bar(instrument_token=88, timeframe=TIMEFRAME, warmup=warmup,
               timestamp=datetime(2026, 9, 10, tzinfo=timezone.utc) + timedelta(days=i),
               open=close, high=close + 1, low=close - 1, close=close, volume=1000.0)


@pytest.mark.asyncio
async def test_warmup_bars_feed_strategies_but_place_no_orders():
    feed = _ListFeed([_bar(0, 100.0, True), _bar(1, 101.0, True), _bar(2, 120.0, False)])
    db = AsyncMongoMockClient()["test_db"]
    ledger = LedgerStore(db, user_id="alice")

    await run(
        strategies=[_BuyEveryBarStrategy()], feed=feed, execution=SimulatedExecutionClient(),
        portfolio=Portfolio(), clock=SimClock(), symbol_for_token=feed.symbol_for_token, ledger=ledger,
    )

    fills = await ledger.get_fills(symbol=SYMBOL)
    assert [f.price for f in fills] == [120.0]  # only the live bar traded, at its own price
