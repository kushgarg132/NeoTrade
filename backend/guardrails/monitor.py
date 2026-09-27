"""Checks every opted-in user's guardrails once a minute during the NSE
session, against their real broker activity: today's trade book (which is
also saved to the journal as a side effect) and the broker's own day P&L.

A new breach is alerted once -- over the socket (topic `guardrails`) and to
Telegram if linked. A daily-loss breach also trips the engine's kill-switch
for the day, so NeoTrade itself stops adding risk.

What this cannot do, and the UI says so: stop an order the user places in
their broker's own app. It alerts; it does not block.

On a daily-loss breach, if the user chose it, open NSE intraday positions
are squared off (square_off.py). "preview" only alerts with the orders it
would place; "live" places them. This is the one path in the app that
places a real order without a per-trade approval, so: it only reduces
exposure, only MIS on NSE, at most once per day (the breach record is
written before any order goes out, so a retry or second worker cannot
repeat it), and only after the user switched it to "live" themselves.
"""

import asyncio
import logging
from datetime import datetime, time, timezone

from backend.auth.broker_credentials import BrokerCredentialStore, fernet_from_settings
from backend.brokers.protocol import BrokerSessionState
from backend.brokers.registry import BROKERS, get_broker_adapter
from backend.engine.session import IST
from backend.guardrails import telegram
from backend.guardrails.rules import evaluate
from backend.guardrails.square_off import describe, exit_orders
from backend.guardrails.store import GuardrailStore
from backend.instruments.master import InstrumentMaster
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
    # Lot sizes for today's options trades, from the broker's NFO dump.
    master = InstrumentMaster(db)
    lot_sizes = {}
    for trip in trips:
        if trip["kind"] in ("CALL", "PUT") and trip["symbol"] not in lot_sizes:
            contract = await master.get("NFO", trip["symbol"])
            if contract is not None:
                lot_sizes[trip["symbol"]] = contract.lot_size

    for breach in evaluate(trips, synced["day_pnl"], prefs, lot_sizes):
        if not await store.record(user_id, day, breach):
            continue
        fresh.append(breach)
        if breach["rule"] == "daily_loss":
            await KillSwitchStore(db).trip(user_id, day, reason="guardrail: daily loss limit",
                                           equity=synced["day_pnl"])
        await _alert(user_id, chat_id, breach)
        if breach["rule"] == "daily_loss" and prefs.get("auto_square_off", "off") in ("preview", "live"):
            for i, alert in enumerate(await square_off(redis, credentials, prefs)):
                event = {"key": f"square_off:{i}", "rule": "square_off", **alert}
                await store.record(user_id, day, event)
                await _alert(user_id, chat_id, event)
    return fresh


async def _alert(user_id: str, chat_id, event: dict) -> None:
    await hub.publish(user_id, "guardrails", "breach", event)
    if chat_id:
        await telegram.send(chat_id, f"NeoTrade: {event['title']}\n{event['detail']}")


async def square_off(redis, credentials, prefs: dict) -> list[dict]:
    """One alert per broker that had anything to close or anything it
    refused to touch. Only called once per user per day: the daily_loss
    breach it hangs off is recorded before this runs."""
    live = prefs.get("auto_square_off") == "live"
    user_id = prefs["user_id"]
    alerts = []
    for broker in BROKERS:
        adapter = await get_broker_adapter(broker, user_id, credentials, redis)
        if await adapter.state() != BrokerSessionState.ACTIVE:
            continue
        try:
            orders, left = exit_orders(await adapter.get_positions())
        except Exception as exc:
            logger.warning("square-off: %s positions failed for %s: %s", broker, user_id, exc)
            alerts.append({"title": f"{broker}: could not read positions to square off",
                           "detail": "Close your intraday positions yourself."})
            continue
        if not orders and not left:
            continue

        lines = []
        if orders and not live:
            lines.append(f"Would place: {describe(orders)}. Preview only, nothing was sent.")
        elif orders:
            placed, failed = [], []
            for order in orders:
                try:
                    await adapter.place_order(order)
                    placed.append(order)
                except Exception as exc:
                    logger.warning("square-off order failed for %s %s: %s", user_id, order.symbol, exc)
                    failed.append(order)
            if placed:
                lines.append(f"Sent: {describe(placed)}.")
            if failed:
                lines.append(f"Failed, close these yourself: {describe(failed)}.")
        if left:
            lines.append(f"Not touched: {', '.join(left)}.")
        alerts.append({"title": f"{broker}: square-off {'sent' if live else 'preview'}",
                       "detail": " ".join(lines)})
    return alerts


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
