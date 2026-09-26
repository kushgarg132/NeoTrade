"""Checks every opted-in user's guardrails once a minute during the NSE
session, against their real broker activity: today's trade book (which is
also saved to the journal as a side effect) and the broker's own day P&L.

A new breach is alerted once -- over the socket (topic `guardrails`) and to
Telegram if linked. A daily-loss breach also trips the engine's kill-switch
for the day, so NeoTrade itself stops adding risk.

What this cannot do, and the UI says so: stop an order the user places in
their broker's own app. It alerts; it does not block. Automatic square-off
is deliberately not here yet -- it would be the first code path that places
real orders without an approval, and it needs each position's product
(MIS/CNC), which the adapters' position books don't carry today.
"""

import asyncio
import logging
from datetime import datetime, time, timezone

from backend.auth.broker_credentials import BrokerCredentialStore, fernet_from_settings
from backend.engine.session import IST
from backend.guardrails import telegram
from backend.guardrails.rules import evaluate
from backend.guardrails.store import GuardrailStore
from backend.journal.roundtrips import build_round_trips
from backend.journal.store import JournalStore
from backend.journal.sync import sync_user_trades
from backend.prefs import PrefsStore
from backend.risk.kill_switch import KillSwitchStore
from backend.ws.hub import hub

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 60
LOCK_KEY = "guardrails:tick"
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 35)


def in_session(now: datetime) -> bool:
    local = now.astimezone(IST)
    return local.weekday() < 5 and SESSION_OPEN <= local.time() <= SESSION_CLOSE


async def check_user(db, redis, credentials, prefs: dict, now: datetime) -> list[dict]:
    """Returns the breaches that were new this time (and so were alerted)."""
    user_id = prefs["user_id"]
    synced = await sync_user_trades(db, redis, credentials, user_id, include_pnl=True)
    if not synced["brokers"]:
        return []

    day = now.astimezone(IST).date()
    start_of_day = datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(timezone.utc)
    trades = await JournalStore(db).list_trades(user_id, since=start_of_day)
    trips = [t for t in build_round_trips(trades) if t["opened_at"] >= start_of_day]

    store = GuardrailStore(db)
    chat_id = await store.telegram_chat(user_id)
    fresh = []
    for breach in evaluate(trips, synced["day_pnl"], prefs):
        if not await store.record(user_id, day, breach):
            continue
        fresh.append(breach)
        if breach["rule"] == "daily_loss":
            await KillSwitchStore(db).trip(user_id, day, reason="guardrail: daily loss limit",
                                           equity=synced["day_pnl"])
        await hub.publish(user_id, "guardrails", "breach", breach)
        if chat_id:
            await telegram.send(chat_id, f"NeoTrade: {breach['title']}\n{breach['detail']}")
    return fresh


async def run_tick(db, redis, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if redis is None or not in_session(now):
        return 0
    # One worker per tick: the lock outlives the tick's own interval slightly
    # less than INTERVAL_SECONDS, so it frees itself before the next one.
    if not await redis.set(LOCK_KEY, "1", nx=True, px=(INTERVAL_SECONDS - 5) * 1000):
        return 0

    credentials = BrokerCredentialStore(db, fernet_from_settings())
    prefs_store = PrefsStore(db)
    checked = 0
    for doc in await db["user_prefs"].find({"guardrails_enabled": True}).to_list(length=None):
        try:
            await check_user(db, redis, credentials, await prefs_store.get(doc["user_id"]), now)
            checked += 1
        except Exception as exc:
            logger.exception("guardrail check failed for %s: %s", doc["user_id"], exc)
    return checked


async def monitor_loop(db, redis) -> None:
    while True:
        try:
            await run_tick(db, redis)
        except Exception as exc:
            logger.exception("guardrail tick failed: %s", exc)
        await asyncio.sleep(INTERVAL_SECONDS)


def start(db, redis) -> asyncio.Task:
    return asyncio.create_task(monitor_loop(db, redis))
