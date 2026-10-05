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
    stale, by_symbol = [], {}
    for trade in open_trades:
        if _day(trade["entry_at"]) != today:
            stale.append(trade)
        else:
            by_symbol.setdefault(trade["symbol"], []).append(trade)

    # A stock can carry several open trades (runs that started empty opened a
    # fresh one for a stock already held): net them into one position.
    positions, holders = {}, {}
    for symbol, trades in by_symbol.items():
        signed = [(1 if t["side"] == "BUY" else -1) * float(t["quantity"]) for t in trades]
        net = sum(signed)
        if net == 0:
            continue
        same_way = [(q, float(t["entry_price"])) for q, t in zip(signed, trades) if (q > 0) == (net > 0)]
        avg = sum(abs(q) * p for q, p in same_way) / sum(abs(q) for q, _ in same_way)
        positions[symbol] = Position(symbol=symbol, quantity=net, avg_price=avg)
        latest = max(trades, key=lambda t: t["entry_at"])
        if latest.get("strategy"):
            holders[symbol] = latest["strategy"]
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
