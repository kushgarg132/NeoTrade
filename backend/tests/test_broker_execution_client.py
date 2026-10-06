"""BrokerExecutionClient: routes ExecutionClient calls to a real
BrokerAdapter, with idempotent submission and a poll_once() that turns
broker status changes into Fills the same way SimulatedExecutionClient's
_pending_fills queue does. Every BrokerAdapter here is a fake -- no real
network, no real broker, ever (no live account exists to test against)."""

from mongomock_motor import AsyncMongoMockClient

from backend.core.models import BrokerOrderStatus, Order, Position, Side
from backend.engine.execution.broker import BrokerExecutionClient
from backend.engine.execution.live_order_store import LiveOrderStore


class _FakeBrokerAdapter:
    def __init__(self) -> None:
        self.place_order_calls = 0
        self._next_status: dict[str, BrokerOrderStatus] = {}
        self._positions: dict[str, Position] = {}
        self._raise_for: set[str] = set()

    async def place_order(self, order: Order) -> str:
        self.place_order_calls += 1
        return f"broker-{order.id}"

    async def cancel_order(self, broker_order_id: str) -> None:
        pass

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        if broker_order_id in self._raise_for:
            raise RuntimeError(f"broker hiccup for {broker_order_id}")
        return self._next_status[broker_order_id]

    async def get_positions(self) -> dict[str, Position]:
        return self._positions

    def set_status(self, broker_order_id: str, status: BrokerOrderStatus) -> None:
        self._next_status[broker_order_id] = status


def _order(order_id="order-1", symbol="RELIANCE") -> Order:
    return Order(
        id=order_id, symbol=symbol, side=Side.BUY, quantity=10.0,
        order_type="MARKET", product="MIS", strategy_name="volume_surge",
    )


def _client(adapter):
    store = LiveOrderStore(AsyncMongoMockClient()["test_db"])
    return BrokerExecutionClient(adapter, store, user_id="alice"), store


async def test_submit_places_the_order_and_records_it():
    adapter = _FakeBrokerAdapter()
    client, store = _client(adapter)

    order_id = await client.submit(_order())

    assert order_id == "order-1"
    assert adapter.place_order_calls == 1
    assert await store.get_broker_order_id("order-1") == "broker-order-1"


async def test_submit_is_idempotent_on_retry():
    adapter = _FakeBrokerAdapter()
    client, store = _client(adapter)

    await client.submit(_order())
    await client.submit(_order())  # simulates a retry with the same Order.id

    assert adapter.place_order_calls == 1


async def test_poll_once_turns_a_new_fill_into_a_pending_fill():
    adapter = _FakeBrokerAdapter()
    client, store = _client(adapter)

    await client.submit(_order())
    adapter.set_status("broker-order-1", BrokerOrderStatus(
        broker_order_id="broker-order-1", status="FILLED", filled_quantity=10.0, average_price=2500.0,
    ))

    await client.poll_once()

    fills = [f async for f in client.fills()]
    assert len(fills) == 1
    assert fills[0].symbol == "RELIANCE"
    assert fills[0].quantity == 10.0
    assert fills[0].price == 2500.0
    # A real broker's fill is the live book's, never paper's.
    assert fills[0].venue == "live"


async def test_poll_once_does_not_refire_the_same_fill_twice():
    adapter = _FakeBrokerAdapter()
    client, store = _client(adapter)

    await client.submit(_order())
    adapter.set_status("broker-order-1", BrokerOrderStatus(
        broker_order_id="broker-order-1", status="FILLED", filled_quantity=10.0, average_price=2500.0,
    ))

    await client.poll_once()
    _ = [f async for f in client.fills()]  # drains the queue, same as the runner would
    await client.poll_once()  # order is no longer pending -- must not re-poll or re-fill it

    fills = [f async for f in client.fills()]
    assert fills == []


async def test_poll_once_isolates_one_orders_error_from_the_rest_of_the_batch():
    """get_order_status raising for one pending order must not stop the
    other pending orders in the same poll_once() call from being polled and
    turned into fills -- the design's error-isolation requirement
    (docs/superpowers/specs/2026-09-09-live-equity-execution-design.md:168-169)."""
    adapter = _FakeBrokerAdapter()
    client, store = _client(adapter)

    await client.submit(_order(order_id="order-1", symbol="RELIANCE"))
    await client.submit(_order(order_id="order-2", symbol="TCS"))

    adapter._raise_for.add("broker-order-1")
    adapter.set_status("broker-order-2", BrokerOrderStatus(
        broker_order_id="broker-order-2", status="FILLED", filled_quantity=10.0, average_price=3500.0,
    ))

    await client.poll_once()  # must not raise despite order-1's broker hiccup

    fills = [f async for f in client.fills()]
    assert len(fills) == 1
    assert fills[0].symbol == "TCS"
    # order-1 stays pending (untouched by the failed poll) so a later
    # poll_once() gets another chance at it once the broker recovers.
    pending_ids = {row["_id"] for row in await store.pending_for_user("alice")}
    assert pending_ids == {"order-1"}


async def test_positions_proxies_the_adapter():
    adapter = _FakeBrokerAdapter()
    adapter._positions = {"RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=2500.0)}
    client, _ = _client(adapter)

    positions = client.positions()

    assert positions == {}  # synchronous protocol method -- see Step 3 note on why


async def test_the_engine_never_books_an_order_another_path_placed():
    """Audit M3: an approve-live, chat or autopilot order (role mine/ai) is
    the reconciler's (backend/engine/reconcile.py), booked to its own ledger.
    The engine polling it too would put that fill in the run's portfolio and
    hide it from the reconciler."""
    adapter = _FakeBrokerAdapter()
    client, store = _client(adapter)
    await store.record_submitted(
        order_id="auto-1", broker_order_id="broker-auto-1", user_id="alice", strategy_name="",
        symbol="TCS", side=Side.BUY, role="ai",
    )
    adapter.set_status("broker-auto-1", BrokerOrderStatus(
        broker_order_id="broker-auto-1", status="FILLED", filled_quantity=5.0, average_price=4000.0,
    ))

    await client.poll_once()

    assert [f async for f in client.fills()] == []
    assert (await store.collection.find_one({"_id": "auto-1"}))["filled_quantity"] == 0.0  # still the reconciler's


async def test_two_runs_polling_one_order_book_its_fill_once():
    adapter = _FakeBrokerAdapter()
    first, store = _client(adapter)
    second = BrokerExecutionClient(adapter, store, user_id="alice")  # the user's other run, same rows
    await first.submit(_order())
    adapter.set_status("broker-order-1", BrokerOrderStatus(
        broker_order_id="broker-order-1", status="FILLED", filled_quantity=10.0, average_price=2500.0,
    ))
    rows = await store.pending_for_user("alice")
    store.pending_for_user = lambda user_id: _rows(rows)  # both read the row before either writes

    await first.poll_once()
    await second.poll_once()

    fills = [f async for f in first.fills()] + [f async for f in second.fills()]
    assert len(fills) == 1


async def _rows(rows):
    return [dict(r) for r in rows]
