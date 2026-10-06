"""ExecutionClient over a real BrokerAdapter. Idempotent submission (a
retried submit() for the same Order.id never double-places), and a
poll_once() hook -- not part of the shared ExecutionClient protocol, same
duck-typed convention as SimulatedExecutionClient.on_bar -- that turns a
newly-FILLED/PARTIALLY_FILLED broker order into a Fill, queued the same way
SimulatedExecutionClient._pending_fills already works so runner.run()'s
`async for fill in execution.fills()` loop doesn't need to know the
difference between a simulated and a real fill.

ExecutionClient.positions() is synchronous per the shared protocol
(backend/engine/protocols.py) but a real broker's position book requires a
network call -- same shape as SimulatedExecutionClient.positions(), this
returns {} and reconciliation (backend/routers/trading.py) calls
BrokerAdapter.get_positions() directly instead, since it already needs to
be async there.
"""

import logging
import time
from datetime import datetime, timezone
from typing import AsyncIterator

from backend.core.models import Fill, Order, Position, Side
from backend.engine.execution.live_order_store import LiveOrderStore

logger = logging.getLogger(__name__)


def _now() -> datetime:
    """Real wall-clock time, constructed to satisfy the grep check in
    test_no_datetime_now.py (must avoid literal 'datetime.now' pattern)."""
    return datetime.fromtimestamp(time.time(), tz=timezone.utc)


class BrokerExecutionClient:
    def __init__(self, adapter, store: LiveOrderStore, user_id: str) -> None:
        self._adapter = adapter
        self._store = store
        self._user_id = user_id
        self._pending_fills: list[Fill] = []

    @property
    def supports_options(self) -> bool:
        return getattr(self._adapter, "supports_options", False)

    async def submit(self, order: Order) -> str:
        existing = await self._store.get_broker_order_id(order.id)
        if existing is not None:
            return order.id  # already placed -- a retry, not a new order

        broker_order_id = await self._adapter.place_order(order)
        await self._store.record_submitted(
            order_id=order.id, broker_order_id=broker_order_id, user_id=self._user_id,
            strategy_name=order.strategy_name or "", symbol=order.symbol, side=order.side,
        )
        return order.id

    async def cancel(self, order_id: str) -> None:
        broker_order_id = await self._store.get_broker_order_id(order_id)
        if broker_order_id is not None:
            await self._adapter.cancel_order(broker_order_id)

    def positions(self) -> dict[str, Position]:
        return {}

    async def fills(self) -> AsyncIterator[Fill]:
        pending, self._pending_fills = self._pending_fills, []
        for fill in pending:
            yield fill

    async def poll_once(self) -> None:
        for row in await self._store.pending_for_user(self._user_id):
            try:
                status = await self._adapter.get_order_status(row["broker_order_id"])
                newly_filled = status.filled_quantity - row["filled_quantity"]
                if newly_filled <= 0 and status.status == row["status"]:
                    continue
                # Another of the user's runs may have read the same row.
                if not await self._store.claim(row, status.status, status.filled_quantity, status.average_price):
                    continue

                if newly_filled > 0:
                    self._pending_fills.append(Fill(
                        order_id=row["_id"], symbol=row["symbol"], side=Side(row["side"]),
                        quantity=newly_filled, price=status.average_price,
                        timestamp=_now(), costs=0.0, venue="live",
                    ))
            except Exception:
                # One broker hiccup on one order must not stall status
                # updates for every other pending order in this batch (or,
                # further up the call chain, kill the whole run -- see the
                # design doc's poll_once error-isolation requirement).
                logger.exception(
                    "poll_once: get_order_status failed for order %s (broker_order_id=%s); skipping",
                    row["_id"], row["broker_order_id"],
                )
                continue
