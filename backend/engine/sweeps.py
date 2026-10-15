"""Once a minute: settle proposals a crash left SENDING (engine/stuck.py) and
book live orders that filled after their first checks (engine/reconcile.py).
Both workers run it; each settles a row with a compare-and-set."""

import asyncio
import logging

from backend.core.clock import SystemClock
from backend.system.jobs import mark

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 60


async def _adapter_for_role(user_id: str, role: str):
    """The logged-in adapter for a user's `role` broker, or None."""
    from backend.auth.broker_credentials import get_credential_store
    from backend.brokers.roles import RoleUnavailable, adapter_for
    from backend.database import db as database

    try:
        return await adapter_for(user_id, role, get_credential_store(), database.redis)
    except RoleUnavailable:
        return None


async def _loop(db) -> None:
    from backend.database import db as database
    from backend.engine.reconcile import reconcile
    from backend.engine.stuck import sweep_stuck

    while True:
        try:
            now = SystemClock().now()
            await sweep_stuck(db, now)
            await reconcile(db, _adapter_for_role, now)
            await mark(database.redis, "order_sweeps", True)
        except Exception as exc:
            logger.exception("order sweeps failed: %s", exc)
            await mark(database.redis, "order_sweeps", False, f"{type(exc).__name__}: {exc}")
        await asyncio.sleep(INTERVAL_SECONDS)


def start(db) -> asyncio.Task:
    return asyncio.create_task(_loop(db))
