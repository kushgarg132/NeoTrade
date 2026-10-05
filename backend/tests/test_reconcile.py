"""Live orders not filled within execute_live_order's few status checks stayed
SUBMITTED forever: their later fills never reached the book, and a SENT
proposal never became EXECUTED. A reconciler asks each order's own broker
(its role: mine or ai) and books only what newly filled."""

from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.models import BrokerOrderStatus
from backend.engine.persistence import LedgerStore
from backend.engine.reconcile import reconcile

NOW = datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc)


class _Broker:
    def __init__(self, status, filled, price=100.0):
        self.status, self.filled, self.price, self.asked = status, filled, price, []

    async def get_order_status(self, broker_order_id):
        import asyncio
        await asyncio.sleep(0)  # a real broker call yields: lets two passes interleave
        self.asked.append(broker_order_id)
        return BrokerOrderStatus(broker_order_id=broker_order_id, status=self.status,
                                 filled_quantity=self.filled, average_price=self.price)


def _adapters(**by_role):
    async def adapter_for(user_id, role):
        return by_role.get(role)
    return adapter_for


@pytest.fixture
def db():
    return AsyncMongoMockClient()["test_db"]


async def _row(db, order_id="o1", role="mine", ledger_user="alice", filled=0.0, status="SUBMITTED"):
    await db["live_orders"].insert_one({"_id": order_id, "broker_order_id": f"B-{order_id}", "user_id": "alice",
                                        "role": role, "ledger_user": ledger_user, "symbol": "ITC", "side": "BUY",
                                        "status": status, "filled_quantity": filled, "average_price": 0.0})


async def test_a_late_fill_is_booked_once(db):
    await _row(db)
    broker = _Broker("FILLED", 10, price=401.5)
    assert await reconcile(db, _adapters(mine=broker), NOW) == 1
    await reconcile(db, _adapters(mine=broker), NOW)  # second pass: nothing new
    fills = await LedgerStore(db, user_id="alice").get_fills(venue="live")
    assert [(f.quantity, f.price) for f in fills] == [(10, 401.5)]
    row = await db["live_orders"].find_one({"_id": "o1"})
    assert (row["status"], row["filled_quantity"]) == ("FILLED", 10)


async def test_only_the_new_part_of_a_partial_fill_is_booked(db):
    await _row(db, filled=4.0, status="PARTIALLY_FILLED")
    await reconcile(db, _adapters(mine=_Broker("FILLED", 10)), NOW)
    fills = await LedgerStore(db, user_id="alice").get_fills(venue="live")
    assert [f.quantity for f in fills] == [6]


async def test_each_order_asks_its_own_broker_and_books_its_own_ledger(db):
    await _row(db, order_id="m1", role="mine", ledger_user="alice")
    await _row(db, order_id="a1", role="ai", ledger_user="alice:autopilot")
    mine, ai = _Broker("FILLED", 1), _Broker("FILLED", 2)
    await reconcile(db, _adapters(mine=mine, ai=ai), NOW)
    assert (mine.asked, ai.asked) == (["B-m1"], ["B-a1"])
    assert [f.quantity for f in await LedgerStore(db, user_id="alice:autopilot").get_fills(venue="live")] == [2]


async def test_a_sent_proposal_becomes_executed_when_its_order_fills(db):
    await _row(db)
    await db["paper_orders"].insert_one({"id": "o1", "user_id": "alice", "suggestion_id": "s1", "status": "PENDING"})
    await db["suggestions"].insert_one({"id": "s1", "user_id": "alice", "status": "SENT"})
    await reconcile(db, _adapters(mine=_Broker("FILLED", 10)), NOW)
    assert (await db["suggestions"].find_one({"id": "s1"}))["status"] == "EXECUTED"


async def test_a_rejection_is_recorded_without_a_fill(db):
    await _row(db)
    await reconcile(db, _adapters(mine=_Broker("REJECTED", 0)), NOW)
    assert (await db["live_orders"].find_one({"_id": "o1"}))["status"] == "REJECTED"
    assert await LedgerStore(db, user_id="alice").get_fills(venue="live") == []


async def test_rows_without_a_role_or_broker_are_left_alone(db):
    await db["live_orders"].insert_one({"_id": "old", "broker_order_id": "B", "user_id": "alice",
                                        "symbol": "ITC", "side": "BUY", "status": "SUBMITTED", "filled_quantity": 0})
    await _row(db, order_id="nobroker", role="ai")
    assert await reconcile(db, _adapters(), NOW) == 0


async def test_two_workers_reconciling_at_once_book_a_fill_once(db):
    import asyncio

    await _row(db)
    broker = _Broker("FILLED", 10)
    await asyncio.gather(reconcile(db, _adapters(mine=broker), NOW), reconcile(db, _adapters(mine=broker), NOW))
    assert len(await LedgerStore(db, user_id="alice").get_fills(venue="live")) == 1
