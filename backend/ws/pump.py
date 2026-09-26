"""Periodic pushes: live prices for watched symbols, and recomputed P&L.

One task for the whole process, not one per connection: the symbols worth
polling are exactly the union of what every open socket subscribed to, and
polling them once serves every viewer.

Prices come from the same best-effort quote fetch the analytics endpoint
uses; when a Kite session is connected its tick feed can replace this
entirely (the hub interface stays the same).
"""

import asyncio
import logging

from backend.analytics import compute_pnl
from backend.engine.persistence import LedgerStore
from backend.marks import mark_prices
from backend.ws.hub import hub

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 15
PNL_TOPIC = "pnl"


async def push_once(db) -> dict:
    symbols = hub.subscribed_symbols()
    marks = await mark_prices(db, symbols) if symbols else {}

    for symbol, price in marks.items():
        for user_id in hub.users_watching(symbol):
            await hub.publish(user_id, f"prices:{symbol}", "tick", {"symbol": symbol, "price": price})

    pnl_users = hub.users_on(PNL_TOPIC)
    for user_id in pnl_users:
        ledger = LedgerStore(db, user_id=user_id)
        positions = await ledger.get_open_positions()
        # Reuse whatever the price pass already fetched; only pay for the
        # symbols this user holds that nobody was watching.
        missing = [s for s in positions if s not in marks]
        user_marks = {**marks, **(await mark_prices(db, missing) if missing else {})}
        # Both books in one message, keyed by venue: the Paper tab reads
        # `paper`, the real-money statement reads `live`, and neither ever
        # shows the other's figures. The combined figures stay at the top
        # level for a browser still running the build from before venues,
        # which reads `today`/`month`/`open` there and would crash without.
        await hub.publish(user_id, PNL_TOPIC, "updated", {
            **await compute_pnl(ledger, user_marks),
            **{venue: await compute_pnl(ledger, user_marks, venue=venue) for venue in ("paper", "live")},
        })

    return {"symbols": len(marks), "pnl_users": len(pnl_users)}


async def pump_loop(db, interval: float = INTERVAL_SECONDS) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await push_once(db)
        except Exception as exc:
            logger.exception("price pump tick failed: %s", exc)


def start(db, interval: float = INTERVAL_SECONDS) -> asyncio.Task:
    return asyncio.create_task(pump_loop(db, interval))
