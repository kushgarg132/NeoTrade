"""LiveOrderStore: collection `live_orders`, one document per app-side
Order.id. Backs BrokerExecutionClient's idempotent submit (Task 7) and the
status-poll loop."""

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.models import Side
from backend.engine.execution.live_order_store import LiveOrderStore


def _store():
    return LiveOrderStore(AsyncMongoMockClient()["test_db"])


@pytest.mark.asyncio
async def test_unrecorded_order_has_no_broker_order_id():
    store = _store()
    assert await store.get_broker_order_id("order-1") is None


@pytest.mark.asyncio
async def test_record_submitted_then_lookup_returns_broker_order_id():
    store = _store()
    await store.record_submitted(
        order_id="order-1", broker_order_id="broker-1", user_id="alice",
        strategy_name="volume_surge", symbol="RELIANCE", side=Side.BUY,
    )
    assert await store.get_broker_order_id("order-1") == "broker-1"


@pytest.mark.asyncio
async def test_claim_changes_pending_membership():
    store = _store()
    await store.record_submitted(
        order_id="order-1", broker_order_id="broker-1", user_id="alice",
        strategy_name="volume_surge", symbol="RELIANCE", side=Side.BUY,
    )
    assert len(await store.pending_for_user("alice")) == 1

    row = (await store.pending_for_user("alice"))[0]
    assert await store.claim(row, status="FILLED", filled_quantity=10.0, average_price=2500.0)

    assert await store.pending_for_user("alice") == []


@pytest.mark.asyncio
async def test_pending_for_user_excludes_another_users_orders():
    store = _store()
    await store.record_submitted(
        order_id="order-1", broker_order_id="broker-1", user_id="alice",
        strategy_name="volume_surge", symbol="RELIANCE", side=Side.BUY,
    )
    assert await store.pending_for_user("bob") == []


@pytest.mark.asyncio
async def test_pending_row_carries_the_orders_side():
    store = _store()
    await store.record_submitted(
        order_id="order-1", broker_order_id="broker-1", user_id="alice",
        strategy_name="volume_surge", symbol="RELIANCE", side=Side.BUY,
    )
    rows = await store.pending_for_user("alice")
    assert rows[0]["side"] == "BUY"
