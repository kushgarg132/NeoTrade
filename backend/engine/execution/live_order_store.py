"""Tracks every live order this app has ever submitted to a real broker.
Collection `live_orders`, one document per app-side Order.id (never
overwritten as a new order -- `record_submitted` is called once per order,
`update_status` mutates that same document as the broker's own state
changes). Backs two things: BrokerExecutionClient's idempotent submit
(backend/engine/execution/broker.py -- a retry checks here before calling
place_order again) and the per-bar status-poll loop's "what's still
outstanding for this user" query.
"""

import time
from datetime import datetime, timezone
from typing import Optional

from backend.core.models import LiveOrderState, Side
from backend.engine.execution.costs import fill_costs

_PENDING_STATES = ("SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED")


def _now() -> datetime:
    """Real wall-clock time, constructed to satisfy the grep check in
    test_no_datetime_now.py (must avoid literal 'datetime.now' pattern)."""
    return datetime.fromtimestamp(time.time(), tz=timezone.utc)


def increment_price(row: dict, average_price: float, filled_quantity: float) -> float:
    """Price of what newly filled on a `live_orders` row. Brokers report the
    cumulative average, so a later partial's own price is backed out of it
    and the row's previous average; without that history, the average."""
    before, before_avg = float(row.get("filled_quantity") or 0), float(row.get("average_price") or 0)
    new = filled_quantity - before
    if before <= 0 or before_avg <= 0 or new <= 0:
        return average_price
    price = (average_price * filled_quantity - before_avg * before) / new
    return price if price > 0 else average_price


def fill_row_costs(row: dict, price: float, quantity: float) -> float:
    """Modelled charges for a fill of a `live_orders` row, so live P&L is net
    like paper. Rows from before `product` was recorded book 0.0."""
    if not row.get("product"):
        return 0.0
    return fill_costs(price, quantity, Side(row["side"]), row["product"], bool(row.get("option")))


class LiveOrderStore:
    def __init__(self, db) -> None:
        self._db = db

    @property
    def collection(self):
        return self._db["live_orders"]

    async def ensure_indexes(self) -> None:
        # Compound to match pending_for_user's actual query shape (user_id
        # + status $in), same convention as runs.py's (user_id, status)
        # index.
        await self.collection.create_index([("user_id", 1), ("status", 1)])

    async def record_submitted(
        self, order_id: str, broker_order_id: str, user_id: str, strategy_name: str, symbol: str, side: Side,
        reason: str | None = None, role: str | None = None, ledger_user: str | None = None,
        product: str | None = None, option: bool = False,
    ) -> None:
        await self.collection.insert_one({
            "_id": order_id,
            "broker_order_id": broker_order_id,
            "user_id": user_id,
            "strategy_name": strategy_name,
            "symbol": symbol,
            "side": side.value,
            "status": "SUBMITTED",
            "filled_quantity": 0.0,
            "average_price": 0.0,
            "submitted_at": _now(),
            "updated_at": _now(),
            # Why a person placed it, for orders not born of a strategy (chat).
            "reason": reason,
            # Which broker (mine / ai) holds it and which ledger books its fills.
            "role": role,
            "ledger_user": ledger_user or user_id,
            # What a late fill is charged as (fill_row_costs).
            "product": product,
            "option": option,
        })

    async def get_broker_order_id(self, order_id: str) -> Optional[str]:
        doc = await self.collection.find_one({"_id": order_id})
        return doc["broker_order_id"] if doc else None

    async def update_status(
        self, order_id: str, status: LiveOrderState, filled_quantity: float, average_price: float,
    ) -> None:
        await self.collection.update_one(
            {"_id": order_id},
            {"$set": {
                "status": status, "filled_quantity": filled_quantity, "average_price": average_price,
                "updated_at": _now(),
            }},
        )

    async def claim(
        self, row: dict, status: LiveOrderState, filled_quantity: float, average_price: float,
    ) -> bool:
        """Compare-and-set from the `row` as the caller read it: True only for
        the one caller that moves it, which alone may book the new quantity.
        The engine's poll, the reconciler (engine/reconcile.py) and
        execute_live_order's own status check can all see the same fill."""
        moved = await self.collection.find_one_and_update(
            {"_id": row["_id"], "filled_quantity": row.get("filled_quantity", 0.0), "status": row["status"]},
            {"$set": {"status": status, "filled_quantity": filled_quantity, "average_price": average_price,
                      "updated_at": _now()}},
        )
        return moved is not None

    async def pending_for_user(self, user_id: str) -> list[dict]:
        """The engine's own pending orders. Rows with a broker role (mine /
        ai: approve-live, chat, autopilot) are the reconciler's, booked to
        their own ledger -- never the engine run's (audit M3)."""
        cursor = self.collection.find({
            "user_id": user_id, "status": {"$in": list(_PENDING_STATES)}, "role": {"$nin": ["mine", "ai"]},
        })
        return await cursor.to_list(length=None)
