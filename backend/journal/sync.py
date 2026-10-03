"""Pull today's trade book from every broker a user has an ACTIVE session
with into their journal. Run on demand (POST /journal/sync) and by the
16:00 IST daily pass, since no broker serves yesterday's trades."""

import logging
from datetime import date, timedelta

from backend.brokers.protocol import BrokerSessionState
from backend.brokers.registry import BROKERS, get_broker_adapter
from backend.engine.session import IST
from backend.journal.store import JournalStore

logger = logging.getLogger(__name__)


async def connected_brokers(redis, credentials, user_id: str) -> list[str]:
    """Brokers this user has a live session with right now."""
    return [
        broker for broker in BROKERS
        if await (await get_broker_adapter(broker, user_id, credentials, redis)).state() == BrokerSessionState.ACTIVE
    ]


async def sync_user_trades(db, redis, credentials, user_id: str, include_pnl: bool = False) -> dict:
    """`include_pnl` also sums each synced broker's own day P&L (realised +
    unrealised across its position book) -- what guardrails check the daily
    loss limit against."""
    store = JournalStore(db)
    imported, synced, failed, day_pnl = 0, [], [], 0.0
    for broker in BROKERS:
        adapter = await get_broker_adapter(broker, user_id, credentials, redis)
        if await adapter.state() != BrokerSessionState.ACTIVE:
            continue
        try:
            trades = await adapter.get_trades()
            if include_pnl:
                positions = await adapter.get_positions()
                day_pnl += sum(p.realized_pnl + p.unrealized_pnl for p in positions.values())
        except Exception as exc:
            # One broker's outage must not stop the others from syncing.
            logger.warning("journal sync: %s failed for %s: %s", broker, user_id, exc)
            failed.append(broker)
            continue
        imported += await store.add_trades(user_id, broker, trades, source="sync")
        synced.append(broker)
    result = {"imported": imported, "brokers": synced, "failed": failed}
    if include_pnl:
        result["day_pnl"] = round(day_pnl, 2)
    return result


HISTORY_CHUNK_DAYS = 31


async def import_upstox_history(db, redis, credentials, user_id: str, start: date, end: date) -> dict:
    """Backfills the journal from Upstox's trade history, a month per request.
    A day that already has fills from the live sync is left alone: the two
    sources may number the same fill differently, and the sync's own copy
    has real times. Importing twice adds nothing (store ids)."""
    adapter = await get_broker_adapter("upstox", user_id, credentials, redis)
    if await adapter.state() != BrokerSessionState.ACTIVE:
        raise ValueError("Upstox is not connected. Log in to Upstox in Settings first.")
    trades, chunk = [], start
    while chunk <= end:
        chunk_end = min(chunk + timedelta(days=HISTORY_CHUNK_DAYS - 1), end)
        trades += await adapter.get_trade_history(chunk, chunk_end)
        chunk = chunk_end + timedelta(days=1)

    store = JournalStore(db)
    synced_days = {
        t["traded_at"].astimezone(IST).date() for t in await store.list_trades(user_id)
        if t["broker"] == "upstox" and t.get("source") != "upstox_history"
    }
    fresh = [t for t in trades if t.traded_at.astimezone(IST).date() not in synced_days]
    skipped_days = {t.traded_at.astimezone(IST).date() for t in trades} & synced_days
    imported = await store.add_trades(user_id, "upstox", fresh, source="upstox_history")
    return {"imported": imported, "fetched": len(trades), "skipped_synced_days": len(skipped_days)}
