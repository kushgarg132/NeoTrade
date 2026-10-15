"""Round-trip tests for LedgerStore against an in-memory Mongo
(mongomock_motor's AsyncMongoMockClient), same fixture pattern as
backend/tests/test_instrument_master.py -- don't invent a second
Mongo-test pattern.
"""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.models import Fill, Order, Position, Side
from backend.engine.persistence import LedgerStore


@pytest.fixture
def ledger():
    client = AsyncMongoMockClient()
    return LedgerStore(client["test_db"], user_id="u1")


def _order(**overrides) -> Order:
    defaults = dict(
        id="o1", symbol="RELIANCE", side=Side.BUY, quantity=10.0,
        order_type="MARKET", product="CNC",
    )
    defaults.update(overrides)
    return Order(**defaults)


def _fill(**overrides) -> Fill:
    defaults = dict(
        order_id="o1", symbol="RELIANCE", side=Side.BUY, quantity=10.0,
        price=2500.0, timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc), costs=12.5,
    )
    defaults.update(overrides)
    return Fill(**defaults)


async def test_record_and_no_direct_getter_for_orders_does_not_crash(ledger):
    # No `get_orders` in the brief's interface -- just confirm record_order
    # round-trips into the raw collection without raising.
    await ledger.record_order(_order())
    doc = await ledger.orders.find_one({"id": "o1"})
    assert doc is not None
    assert doc["symbol"] == "RELIANCE"
    assert doc["product"] == "CNC"


async def test_record_and_get_fills(ledger):
    await ledger.record_fill(_fill())
    await ledger.record_fill(_fill(order_id="o2", symbol="TCS", price=3500.0))

    all_fills = await ledger.get_fills()
    assert len(all_fills) == 2

    reliance_only = await ledger.get_fills(symbol="RELIANCE")
    assert len(reliance_only) == 1
    assert reliance_only[0].symbol == "RELIANCE"
    assert reliance_only[0].side == Side.BUY
    assert reliance_only[0].price == 2500.0


async def test_get_fills_filters_by_since(ledger):
    early = datetime(2024, 1, 1, tzinfo=timezone.utc)
    late = datetime(2024, 6, 1, tzinfo=timezone.utc)
    await ledger.record_fill(_fill(order_id="o1", timestamp=early))
    await ledger.record_fill(_fill(order_id="o2", timestamp=late))

    since_mid = await ledger.get_fills(since=datetime(2024, 3, 1, tzinfo=timezone.utc))
    assert len(since_mid) == 1
    assert since_mid[0].order_id == "o2"


async def test_snapshot_and_get_open_positions(ledger):
    positions = {
        "RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=2500.0),
        "TCS": Position(symbol="TCS", quantity=0.0, avg_price=0.0),  # closed -- not "open"
    }
    await ledger.snapshot_positions(positions)

    open_positions = await ledger.get_open_positions()
    assert set(open_positions.keys()) == {"RELIANCE"}
    assert open_positions["RELIANCE"].quantity == 10.0


async def test_snapshot_upserts_same_symbol(ledger):
    await ledger.snapshot_positions({"RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=2500.0)})
    await ledger.snapshot_positions({"RELIANCE": Position(symbol="RELIANCE", quantity=20.0, avg_price=2600.0)})

    open_positions = await ledger.get_open_positions()
    assert len(open_positions) == 1
    assert open_positions["RELIANCE"].quantity == 20.0


@pytest.mark.asyncio
async def test_a_fill_never_grows_a_trade_on_the_other_side(ledger):
    from backend.core.models import Order, Side
    from backend.suggestions.service import fill_on_paper

    now = datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc)

    def order(side, qty, product="MIS"):
        return Order(id=str(uuid.uuid4()), symbol="X", side=side, quantity=qty, order_type="MARKET",
                     limit_price=None, product=product)

    await fill_on_paper(ledger, order(Side.BUY, 10), 100.0, now)
    await fill_on_paper(ledger, order(Side.SELL, 30), 100.0, now)  # flips long 10 -> short 20

    trades = {t["side"]: t for t in await ledger.get_trades()}
    assert trades["BUY"]["status"] == "CLOSED" and trades["BUY"]["quantity"] == 10
    assert trades["SELL"]["status"] == "OPEN" and trades["SELL"]["quantity"] == 20


@pytest.mark.asyncio
async def test_a_delivery_sell_above_the_long_held_is_refused(ledger):
    from backend.core.models import Order, Side
    from backend.suggestions.service import fill_on_paper

    now = datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc)
    sell = Order(id="s1", symbol="X", side=Side.SELL, quantity=5, order_type="MARKET", limit_price=None, product="CNC")
    with pytest.raises(ValueError):
        await fill_on_paper(ledger, sell, 100.0, now)
    assert await ledger.get_open_positions() == {}


@pytest.mark.asyncio
async def test_a_flipped_trade_books_only_its_own_realized_pnl(ledger):
    from backend.core.models import Order, Side
    from backend.suggestions.service import fill_on_paper

    now = datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc)

    def order(side, qty):
        return Order(id=str(uuid.uuid4()), symbol="X", side=side, quantity=qty, order_type="MARKET",
                     limit_price=None, product="MIS")

    await fill_on_paper(ledger, order(Side.BUY, 10), 100.0, now)
    await fill_on_paper(ledger, order(Side.SELL, 20), 110.0, now)  # +100 on the long, then short 10 @110
    await fill_on_paper(ledger, order(Side.BUY, 10), 105.0, now)   # +50 on the short

    pnl = {t["side"]: t["realized_pnl"] for t in await ledger.get_trades(status="CLOSED")}
    assert pnl == {"BUY": 100.0, "SELL": 50.0}
