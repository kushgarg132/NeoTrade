"""Backtests fill a market order at the NEXT bar's open: the signal bar is
only known once it has closed, so filling at its own close was a zero-latency
fill no trader gets. Paper trading keeps filling at the live mark."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.core.models import Bar, Order, Side
from backend.engine.execution.simulated import SimulatedExecutionClient

T0 = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)


def _bar(i, open_, close):
    return Bar(instrument_token=1, timeframe="5m", timestamp=T0 + timedelta(minutes=5 * i),
               open=open_, high=max(open_, close) + 1, low=min(open_, close) - 1, close=close, volume=1.0)


def _order():
    return Order(id="o1", symbol="ITC", side=Side.BUY, quantity=10, order_type="MARKET", product="MIS")


async def _fills(client):
    return [f async for f in client.fills()]


@pytest.mark.asyncio
async def test_a_backtest_order_fills_at_the_next_bars_open():
    client = SimulatedExecutionClient(fill_on_next_open=True)
    client.on_bar("ITC", _bar(0, 100.0, 101.0))
    await client.submit(_order())
    assert await _fills(client) == []  # nothing on the signal bar
    client.on_bar("ITC", _bar(1, 103.0, 104.0))
    (fill,) = await _fills(client)
    assert (fill.price, fill.timestamp) == (103.0, T0 + timedelta(minutes=5))


@pytest.mark.asyncio
async def test_an_order_with_no_next_bar_never_fills():
    client = SimulatedExecutionClient(fill_on_next_open=True)
    client.on_bar("ITC", _bar(0, 100.0, 101.0))
    await client.submit(_order())
    assert await _fills(client) == []


@pytest.mark.asyncio
async def test_paper_still_fills_at_the_current_mark():
    client = SimulatedExecutionClient()
    client.on_bar("ITC", _bar(0, 100.0, 101.0))
    await client.submit(_order())
    (fill,) = await _fills(client)
    assert fill.price == 101.0


@pytest.mark.asyncio
async def test_fill_now_books_at_a_given_level():
    client = SimulatedExecutionClient(fill_on_next_open=True)
    client.on_bar("ITC", _bar(0, 100.0, 101.0))
    await client.fill_now(_order(), 97.5, T0)
    (fill,) = await _fills(client)
    assert fill.price == 97.5
