"""Pull today's trade book from every broker a user has an ACTIVE session
with into their journal. Run on demand (POST /journal/sync) and by the
16:00 IST daily pass, since no broker serves yesterday's trades."""

import logging

from backend.brokers.protocol import BrokerSessionState
from backend.brokers.registry import BROKERS, get_broker_adapter
from backend.journal.store import JournalStore

logger = logging.getLogger(__name__)


async def sync_user_trades(db, redis, credentials, user_id: str) -> dict:
    store = JournalStore(db)
    imported, synced, failed = 0, [], []
    for broker in BROKERS:
        adapter = await get_broker_adapter(broker, user_id, credentials, redis)
        if await adapter.state() != BrokerSessionState.ACTIVE:
            continue
        try:
            trades = await adapter.get_trades()
        except Exception as exc:
            # One broker's outage must not stop the others from syncing.
            logger.warning("journal sync: %s failed for %s: %s", broker, user_id, exc)
            failed.append(broker)
            continue
        imported += await store.add_trades(user_id, broker, trades, source="sync")
        synced.append(broker)
    return {"imported": imported, "brokers": synced, "failed": failed}
