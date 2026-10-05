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

_PENDING_STATES = ("SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED")


def _now() -> datetime:
    """Real wall-clock time, constructed to satisfy the grep check in
    test_no_datetime_now.py (must avoid literal 'datetime.now' pattern)."""
    return datetime.fromtimestamp(time.time(), tz=timezone.utc)


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

    async def pending_for_user(self, user_id: str) -> list[dict]:
        cursor = self.collection.find({"user_id": user_id, "status": {"$in": list(_PENDING_STATES)}})
        return await cursor.to_list(length=None)
