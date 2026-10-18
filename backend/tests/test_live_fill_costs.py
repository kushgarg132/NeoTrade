"""Live fills were booked with costs=0.0, so live P&L was gross while paper and
backtest were net. Every live booking path now charges the same modelled
schedule as a paper fill of the same order."""

from datetime import datetime, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.core.models import BrokerOrderStatus, Order, Side
from backend.engine.execution.broker import BrokerExecutionClient
from backend.engine.execution.costs import calculate_indian_costs
from backend.engine.execution.live_order_store import LiveOrderStore
from backend.engine.persistence import LedgerStore
from backend.engine.reconcile import reconcile
from backend.suggestions.service import execute_live_order


class _Broker:
    async def place_order(self, order):
        return f"B-{order.id}"

    async def get_order_status(self, broker_order_id):
        return BrokerOrderStatus(broker_order_id=broker_order_id, status="FILLED",
                                 filled_quantity=10, average_price=400.0)


def _order(product="MIS"):
    return Order(id="o1", symbol="ITC", side=Side.BUY, quantity=10, order_type="MARKET",
                 product=product, strategy_name="s")


async def test_engine_poll_charges_a_live_fill():
    client = BrokerExecutionClient(_Broker(), LiveOrderStore(AsyncMongoMockClient()["t"]), user_id="alice")
    await client.submit(_order())
    await client.poll_once()
    [fill] = [f async for f in client.fills()]
    assert fill.costs == calculate_indian_costs(400.0, 10, Side.BUY, "MIS") > 0


async def test_execute_live_order_charges_the_fill():
    db = AsyncMongoMockClient()["t"]
    ledger = LedgerStore(db, user_id="alice")
    await execute_live_order(_order("CNC"), ledger, _Broker(), LiveOrderStore(db))
    [fill] = await ledger.get_fills(venue="live")
    assert fill.costs == calculate_indian_costs(400.0, 10, Side.BUY, "CNC") > 0


async def test_reconciler_charges_a_late_fill_and_leaves_legacy_rows_at_zero():
    db = AsyncMongoMockClient()["t"]
    store = LiveOrderStore(db)
    await store.record_submitted("o1", "B-o1", "alice", "s", "ITC", Side.BUY, role="mine", product="MIS")
    await store.record_submitted("o2", "B-o2", "alice", "s", "ITC", Side.BUY, role="mine")  # no product: legacy

    async def adapter_for(user_id, role):
        return _Broker()
    await reconcile(db, adapter_for, datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc))

    fills = {f.order_id: f.costs for f in await LedgerStore(db, user_id="alice").get_fills(venue="live")}
    assert fills == {"o1": calculate_indian_costs(400.0, 10, Side.BUY, "MIS"), "o2": 0.0}
