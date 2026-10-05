"""What a new intraday run inherits. A restart (every deploy) used to start
each run from an empty portfolio, so open intraday positions were forgotten:
never squared off, invisible to the per-stock cap, exposure and the kill
switch. Today's open intraday trades are adopted with the strategy that owns
them; older ones (an intraday position cannot outlive its day) are closed at
their mark. Time is passed in: this module must not read the clock itself.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from backend.core.models import Order, Position, Side
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST
from backend.suggestions.service import fill_on_paper

logger = logging.getLogger(__name__)


def _day(value: datetime):
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(IST).date()


async def adopt_intraday(db, user_id: str, now: datetime) -> tuple[dict[str, Position], dict[str, str], list[dict]]:
    """(positions, holders, stale): today's open intraday paper trades as
    positions plus their owning strategy; earlier days' as trades to close."""
    open_trades = await db["paper_trades"].find(
        {"user_id": user_id, "mode": "INTRADAY", "status": "OPEN", "venue": {"$in": ["paper", None]}}
    ).to_list(length=None)
    today = now.astimezone(IST).date()
    positions, holders, stale = {}, {}, []
    for trade in open_trades:
        if _day(trade["entry_at"]) != today:
            stale.append(trade)
            continue
        sign = 1 if trade["side"] == "BUY" else -1
        positions[trade["symbol"]] = Position(
            symbol=trade["symbol"], quantity=sign * float(trade["quantity"]), avg_price=float(trade["entry_price"]),
        )
        if trade.get("strategy"):
            holders[trade["symbol"]] = trade["strategy"]
    return positions, holders, stale


async def close_stale(
    ledger: LedgerStore, stale: list[dict], mark_price: Callable[[str], Awaitable[float]], now: datetime,
) -> int:
    """Closes each stale intraday trade at its mark; one without a price is
    left for the next run start. Returns how many were closed."""
    closed = 0
    for trade in stale:
        try:
            price = await mark_price(trade["symbol"])
        except Exception as exc:
            logger.warning("stale intraday %s not closed this time: %s", trade["symbol"], exc)
            continue
        order = Order(
            id=str(uuid.uuid4()), symbol=trade["symbol"],
            side=Side.SELL if trade["side"] == "BUY" else Side.BUY,
            quantity=float(trade["quantity"]), order_type="MARKET", product="MIS",
            strategy_name=trade.get("strategy"),
        )
        await fill_on_paper(ledger, order, price, now)
        logger.info("closed stale intraday %s %s at %.2f", trade["symbol"], trade["side"], price)
        closed += 1
    return closed
