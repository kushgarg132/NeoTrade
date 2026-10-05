"""Live engine orders on the AI account, through the autopilot.

AGENTS.md: only backend/autopilot/ may place orders on the `ai` account, and
only after its fence passes. A strategy that earned its live switch therefore
hands each order to autopilot.service.submit (source "engine"): the fence's
capital, per-trade cap, trades/day, Nifty 200 and no-short checks apply, the
kill switch still applies, and the fill books to the AI ledger. Nothing is
booked to the engine's own ledger, so no fill is reported back here.
"""

import logging
from typing import AsyncIterator

from backend.core.models import Fill, Order

logger = logging.getLogger(__name__)


class AutopilotExecutionClient:
    def __init__(self, db, redis, user_id: str) -> None:
        self._db, self._redis, self._user_id = db, redis, user_id

    async def submit(self, order: Order) -> None:
        from backend.autopilot import service

        result = await service.submit(self._db, self._redis, self._user_id, service.AutopilotOrder(
            symbol=order.symbol, side=order.side, quantity=int(order.quantity),
            product="MIS" if order.product == "MIS" else "CNC", source="engine",
            reason=f"Engine: {order.strategy_name or 'strategy'} signal",
        ))
        if result.get("status") not in ("FILLED", "SENT"):
            logger.info("autopilot refused engine order %s %s: %s", order.side.value, order.symbol, result.get("reason"))

    async def fills(self) -> AsyncIterator[Fill]:
        return
        yield  # an async generator that yields nothing
