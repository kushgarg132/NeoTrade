"""Orders placed from the chat: attributed to "chat" on paper, and placed
live through the same path an approved option proposal uses."""

from datetime import datetime, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.core.models import BrokerOrderStatus, Order, Side
from backend.engine.execution.live_order_store import LiveOrderStore
from backend.engine.persistence import LedgerStore
from backend.suggestions.service import execute_live_order, execute_suggestion


class _Broker:
    def __init__(self):
        self.placed = []

    async def place_order(self, order):
        self.placed.append(order)
        return "B1"

    async def get_order_status(self, broker_order_id):
        return BrokerOrderStatus(broker_order_id=broker_order_id, status="FILLED", filled_quantity=10, average_price=1501.0)


async def test_paper_chat_order_is_attributed_to_chat():
    db = AsyncMongoMockClient()["test_db"]
    ledger = LedgerStore(db, user_id="alice")
    order = await execute_suggestion(
        {"symbol": "INFY", "side": "BUY", "quantity": 10, "mode": "LONGTERM"}, ledger, 1500.0, strategy_name="chat",
    )
    trades = await ledger.get_trades()
    assert order.product == "CNC"
    assert trades[0]["strategy"] == "chat"


async def test_live_equity_order_books_the_broker_fill():
    db = AsyncMongoMockClient()["test_db"]
    ledger = LedgerStore(db, user_id="alice")
    broker = _Broker()
    order = Order(id="o1", symbol="INFY", side=Side.BUY, quantity=10, order_type="MARKET", product="CNC", strategy_name="chat")

    _, status, filled = await execute_live_order(order, ledger, broker, LiveOrderStore(db), "chat", "buy 10 infy")

    assert (status, filled) == ("FILLED", 10)
    fills = await ledger.get_fills(venue="live")
    assert (fills[0].venue, fills[0].price) == ("live", 1501.0)
    record = await db["live_orders"].find_one({"_id": "o1"})
    assert (record["reason"], record["strategy_name"]) == ("buy 10 infy", "chat")


async def test_a_fill_the_reconciler_booked_meanwhile_is_not_booked_twice():
    """Audit M3: execute_live_order checks status for a few seconds; the
    reconciler loop can see the fill in that window and book it first."""
    from backend.engine.reconcile import reconcile

    db = AsyncMongoMockClient()["test_db"]
    ledger = LedgerStore(db, user_id="alice")
    order = Order(id="o1", symbol="INFY", side=Side.BUY, quantity=10, order_type="MARKET", product="CNC", strategy_name="chat")

    class _RacedBroker(_Broker):
        async def get_order_status(self, broker_order_id):
            async def adapter_for(user_id, role):
                return _Broker()
            await reconcile(db, adapter_for, now=datetime.now(timezone.utc))  # the other loop, mid-wait
            return await super().get_order_status(broker_order_id)

    await execute_live_order(order, ledger, _RacedBroker(), LiveOrderStore(db), "chat", "buy 10 infy")

    fills = await ledger.get_fills(venue="live")
    assert [f.quantity for f in fills] == [10]
