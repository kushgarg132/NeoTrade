"""Settles rows a crash left between claim and settle.

A proposal claimed SENDING (backend/routers/suggestions.py) or a resting paper
limit claimed FILLING (backend/engine/paper_orders.py) stays there forever if
the worker dies before it settles. Older than STALE, each is checked against
what actually happened: a booked fill or a broker order settles it; a paper
claim that placed nothing goes back to PENDING; a live claim with no record is
flagged NEEDS_REVIEW, never re-armed -- the order may have reached the broker
in the moment before it was recorded. Time is passed in.
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

STALE = timedelta(minutes=5)


def _aware(value):
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


async def sweep_stuck(db, now: datetime) -> int:
    cutoff = now - STALE
    changed = 0

    async for s in db["suggestions"].find({"status": "SENDING"}):
        claimed = _aware(s.get("decided_at"))
        if claimed is not None and claimed > cutoff:
            continue
        order = await db["paper_orders"].find_one(
            {"user_id": s["user_id"], "suggestion_id": s["id"]}, sort=[("_id", -1)])
        if order is not None and await db["live_orders"].find_one({"_id": order["id"]}):
            status, fields = "SENT", {"order_id": order["id"], "venue": "live",
                                      "reason": "Placed with your broker, not filled yet"}
        elif order is not None and await db["paper_fills"].find_one({"order_id": order["id"]}):
            status, fields = "EXECUTED", {"order_id": order["id"], "reason": None}
        elif order is None and s.get("reason") == "paper":
            status, fields = "PENDING", {"reason": "The approval was interrupted; nothing was placed."}
        else:
            status, fields = "NEEDS_REVIEW", {
                "reason": "An approval was interrupted. Check your broker's order book before approving again."}
        result = await db["suggestions"].update_one(
            {"id": s["id"], "user_id": s["user_id"], "status": "SENDING"}, {"$set": {"status": status, **fields}})
        if result.modified_count:
            logger.warning("stuck proposal %s settled as %s", s["id"], status)
            changed += 1

    async for doc in db["paper_orders"].find({"status": "FILLING"}):
        claimed = _aware(doc.get("claimed_at"))
        if claimed is not None and claimed > cutoff:
            continue
        fill = await db["paper_fills"].find_one({"order_id": doc["id"]})
        update = ({"status": "FILLED", "fill_price": fill.get("price"), "filled_at": fill.get("timestamp")}
                  if fill else {"status": "OPEN"})
        result = await db["paper_orders"].update_one({"_id": doc["_id"], "status": "FILLING"}, {"$set": update})
        if result.modified_count:
            logger.warning("stuck paper limit %s settled as %s", doc["id"], update["status"])
            changed += 1
    return changed
