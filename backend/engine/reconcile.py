"""Follows live orders after they are sent.

execute_live_order checks an order's status for a few seconds; one still open
after that (a resting limit, a slow fill) stayed SUBMITTED forever, its later
fill never booked and its SENT proposal never EXECUTED. Every pending row
names its broker role (mine / ai) and the ledger it books to; this asks that
broker and books only what newly filled. Rows from before roles were recorded
are left alone: there is no safe guess which broker they belong to. Time is
passed in.
"""

import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional

from backend.core.models import Fill, Side
from backend.engine.execution.live_order_store import _PENDING_STATES
from backend.engine.persistence import LedgerStore

logger = logging.getLogger(__name__)

AdapterFor = Callable[[str, str], Awaitable[Optional[object]]]


async def reconcile(db, adapter_for: AdapterFor, now: datetime) -> int:
    from backend.suggestions.service import _book

    changed = 0
    rows = await db["live_orders"].find(
        {"status": {"$in": list(_PENDING_STATES)}, "role": {"$in": ["mine", "ai"]}}
    ).to_list(length=None)
    for row in rows:
        try:
            adapter = await adapter_for(row["user_id"], row["role"])
            if adapter is None:
                continue
            status = await adapter.get_order_status(row["broker_order_id"])
        except Exception as exc:
            logger.warning("live order %s not reconciled this pass: %s", row["_id"], exc)
            continue

        before = float(row.get("filled_quantity") or 0)
        new = float(status.filled_quantity) - before
        if new > 0 or status.status != row["status"]:
            # Compare-and-set on what was filled: both workers run this loop,
            # and only the one that moves the row may book the new quantity.
            claimed = await db["live_orders"].find_one_and_update(
                {"_id": row["_id"], "filled_quantity": row.get("filled_quantity", 0), "status": row["status"]},
                {"$set": {"status": status.status, "filled_quantity": status.filled_quantity,
                          "average_price": status.average_price, "updated_at": now}},
            )
            if claimed is None:
                continue
            if new > 0:
                await _book(LedgerStore(db, user_id=row.get("ledger_user") or row["user_id"]), Fill(
                    order_id=row["_id"], symbol=row["symbol"], side=Side(row["side"]), quantity=new,
                    price=status.average_price, timestamp=now, costs=0.0, venue="live",
                ))
            changed += 1
            logger.info("live order %s now %s (%s filled)", row["_id"], status.status, status.filled_quantity)

        if status.filled_quantity > 0:
            ledger_order = await db["paper_orders"].find_one({"id": row["_id"], "suggestion_id": {"$ne": None}})
            if ledger_order is not None:
                await db["suggestions"].update_one(
                    {"id": ledger_order["suggestion_id"], "user_id": row["user_id"], "status": "SENT"},
                    {"$set": {"status": "EXECUTED", "reason": None, "filled_quantity": status.filled_quantity}},
                )
    return changed
