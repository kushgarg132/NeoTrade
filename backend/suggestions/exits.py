"""Closing approved long-term paper positions at their stop or target.

A long-term proposal is approved together with its stop and target; nothing
else ever sells it. This checks every open long-term paper long against the
proposal that opened it and, when the mark has crossed either level, sells
the whole position on paper at that mark -- the same fill path an approval
uses (service.fill_on_paper). Paper only: a live position is the broker's.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.core.models import Order, Side
from backend.engine.persistence import LedgerStore
from backend.marks import mark_prices
from backend.suggestions.service import fill_on_paper
from backend.ws.publish import publisher_for

logger = logging.getLogger(__name__)


def breach(mark: float, stop: Optional[float], target: Optional[float]) -> Optional[str]:
    """Which level a long position's mark has crossed, if any. Stop wins a
    tie: a mark at or under the stop is a loss to cut, whatever the target."""
    if stop is not None and mark <= stop:
        return "stop"
    if target is not None and mark >= target:
        return "target"
    return None


async def check_exits(db, user_id: str, now: Optional[datetime] = None, marks_fn=mark_prices) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    ledger = LedgerStore(db, user_id=user_id, on_change=publisher_for(user_id))
    trades = [
        t for t in await ledger.get_trades(status="OPEN", venue="paper", mode="LONGTERM", limit=1000)
        # The autopilot's paper trades share this book; it exits its own, through its fence.
        if t["side"] == "BUY" and t.get("suggestion_id") and not (t.get("strategy") or "").startswith("autopilot:")
    ]
    if not trades:
        return []

    suggestions = {
        s["id"]: s for s in await db["suggestions"].find(
            {"user_id": user_id, "id": {"$in": [t["suggestion_id"] for t in trades]}}
        ).to_list(length=None)
    }
    marks = await marks_fn(db, {t["symbol"] for t in trades})

    closed = []
    for trade in trades:
        suggestion = suggestions.get(trade["suggestion_id"])
        mark = marks.get(trade["symbol"])
        if suggestion is None or mark is None:
            continue
        reason = breach(mark, suggestion.get("stop"), suggestion.get("target"))
        if reason is None:
            continue
        order = Order(
            id=str(uuid.uuid4()), symbol=trade["symbol"], side=Side.SELL, quantity=trade["quantity"],
            order_type="MARKET", limit_price=None, product="CNC",
            strategy_name=trade.get("strategy"), suggestion_id=trade["suggestion_id"],
        )
        await fill_on_paper(ledger, order, mark, now)
        gross = (mark - trade["entry_price"]) * trade["quantity"]
        closed.append({
            "symbol": trade["symbol"], "reason": reason, "price": mark,
            "quantity": trade["quantity"], "entry_price": trade["entry_price"], "gross_pnl": gross,
        })
        logger.info("auto-exit %s for %s at %s (%s)", trade["symbol"], user_id, mark, reason)
    return closed
