"""Runs an autopilot order: fence -> paper fill (or, in live mode, the AI
account's broker) -> log -> Telegram note with a one-tap stop."""

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from typing import Literal, Optional

from backend.autopilot import fence
from backend.brokers.roles import RoleUnavailable, adapter_for
from backend.core.models import Order, Side
from backend.engine.autorun import in_session
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST
from backend.marks import mark_prices
from backend.prefs import PrefsStore

logger = logging.getLogger(__name__)
STOP_BUTTON = [[{"text": "🛑 Stop autopilot", "callback_data": "nt:autopilot:off"}]]
LOCK_MS = 30_000
_LOCKS: dict[str, asyncio.Lock] = {}  # per user, in this process; Redis covers the other workers


def ledger_user(user_id: str) -> str:
    """The autopilot's own ledger namespace, so its positions never merge
    with the engine's or the user's own trades of the same symbol."""
    return f"{user_id}:autopilot"


@dataclass
class AutopilotOrder:
    symbol: str
    side: Side
    quantity: int
    product: Literal["CNC", "MIS"]
    source: Literal["chat", "engine", "factor"]
    reason: str
    suggestion_id: Optional[str] = None


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _notify(db, user_id: str, text: str, stop_button: bool = True) -> bool:
    from backend.guardrails import telegram
    from backend.guardrails.store import GuardrailStore

    channel = await GuardrailStore(db).telegram_channel(user_id)
    if channel is None:
        return False
    token, chat_id = channel
    if stop_button:
        return await telegram.send_buttons(chat_id, text, STOP_BUTTON, token)
    return await telegram.send(chat_id, text, token)


async def _state(db, user_id: str, prefs: dict, venue: str, now: datetime) -> fence.FenceState:
    from backend.risk.kill_switch import KillSwitchStore

    day = now.astimezone(IST).date()
    day_start = datetime.combine(day, time(0, 0), tzinfo=IST)
    ledger = LedgerStore(db, user_id=ledger_user(user_id))
    mine = await ledger.get_trades(limit=1000, venue=venue)
    open_trades = [t for t in mine if t.get("status") == "OPEN"]
    marks = await mark_prices(db, {t["symbol"] for t in open_trades}) if open_trades else {}
    deployed = sum(t["quantity"] * marks.get(t["symbol"], t.get("entry_price") or 0) for t in open_trades)
    unrealized = sum((marks.get(t["symbol"], t.get("entry_price") or 0) - (t.get("entry_price") or 0)) * t["quantity"]
                     for t in open_trades)
    realized = sum(t.get("realized_pnl") or 0 for t in mine
                   if t.get("status") == "CLOSED" and (_aware(t.get("exit_at")) or day_start) >= day_start)
    # A live order sent but not confirmed filled still counts until reconciled.
    entries = await db["autopilot_log"].count_documents(
        {"user_id": user_id, "status": {"$in": ["FILLED", "SENT"]}, "side": "BUY", "at": {"$gte": day_start}})
    held = {t["symbol"]: (t["quantity"], _product(t)) for t in open_trades}
    async for row in db["autopilot_log"].find({"user_id": user_id, "status": "SENT", "side": "BUY",
                                               "at": {"$gte": day_start}}):
        held.setdefault(row["symbol"], (row["quantity"], row.get("product") or "CNC"))
        deployed += row["quantity"] * (row.get("price") or 0)
    state = await db["autopilot_state"].find_one({"_id": user_id}) or {}
    tripped = state.get("tripped_day") == day.isoformat()
    if not tripped and realized + unrealized <= -prefs["autopilot_daily_loss_limit"]:
        tripped = True
        await db["autopilot_state"].update_one({"_id": user_id}, {"$set": {"tripped_day": day.isoformat(),
                                                                          "user_id": user_id}}, upsert=True)
    tripped = tripped or bool(await KillSwitchStore(db).is_tripped(user_id, day))
    return fence.FenceState(deployed=deployed, entries_today=entries, held=held,
                            kill_tripped=tripped, session_ok=in_session(now))


def _product(trade: dict) -> str:
    return "MIS" if trade.get("mode") == "INTRADAY" or trade.get("product") == "MIS" else "CNC"


async def _record(db, user_id: str, order: AutopilotOrder, status: str, now: datetime, quiet: bool = False,
                  **extra) -> dict:
    row = {"user_id": user_id, "at": now, "status": status, **asdict(order), "side": order.side.value, **extra}
    await db["autopilot_log"].insert_one(dict(row))
    verb = "bought" if order.side == Side.BUY else "sold"
    if status == "FILLED":
        text = (f"🤖 AI {verb} {order.quantity} {order.symbol} on the AI account"
                f"{' (paper)' if extra.get('mode') == 'paper' else ''} at ₹{extra.get('price', 0):,.2f}.\n{order.reason}")
    else:
        text = f"🤖 Autopilot refused {order.side.value} {order.quantity} {order.symbol}: {extra.get('reason')}"
    if not quiet:
        await _notify(db, user_id, text)
    return {"status": status, **extra}


async def submit(db, redis, user_id: str, order: AutopilotOrder, now: Optional[datetime] = None,
                 suggestion_id: Optional[str] = None, quiet: bool = False) -> dict:
    """Fence -> order -> log, one order at a time per user (the fence reads
    what is held, then the fill changes it: parallel calls must not both pass)."""
    lock = _LOCKS.setdefault(user_id, asyncio.Lock())
    async with lock:
        key = f"autopilot:lock:{user_id}"
        token = str(uuid.uuid4())
        if redis is not None:
            for _ in range(50):
                if await redis.set(key, token, nx=True, px=LOCK_MS):
                    break
                await asyncio.sleep(0.2)
            else:
                return await _record(db, user_id, order, "REFUSED", now or datetime.now(timezone.utc), quiet=quiet,
                                     reason="Another autopilot order is in progress; try again.")
        try:
            return await _submit(db, redis, user_id, order, now or datetime.now(timezone.utc),
                                 suggestion_id or order.suggestion_id, quiet)
        finally:
            # Only our own lock: after its TTL another worker may hold the key.
            if redis is not None and await redis.get(key) in (token, token.encode()):
                await redis.delete(key)


async def _submit(db, redis, user_id: str, order: AutopilotOrder, now: datetime, suggestion_id: Optional[str],
                  quiet: bool) -> dict:
    from backend.suggestions.service import execute_live_order, fill_on_paper

    prefs = await PrefsStore(db).get(user_id)
    live = bool(prefs.get("autopilot_live"))
    mode = "live" if live else "paper"
    price = (await mark_prices(db, {order.symbol})).get(order.symbol)
    if not price:
        return await _record(db, user_id, order, "REFUSED", now, quiet, reason=f"No live price for {order.symbol}.")
    reason = fence.check(order, price, await _state(db, user_id, prefs, mode, now), prefs)
    adapter = None
    if reason is None and live:
        from backend.auth.broker_credentials import get_credential_store
        try:
            adapter = await adapter_for(user_id, "ai", get_credential_store(), redis)
        except RoleUnavailable as exc:
            reason = exc.reason
    if reason:
        return await _record(db, user_id, order, "REFUSED", now, quiet, reason=reason, mode=mode)

    ledger = LedgerStore(db, user_id=ledger_user(user_id))
    placed = Order(id=str(uuid.uuid4()), symbol=order.symbol, side=order.side, quantity=order.quantity,
                   order_type="MARKET", product=order.product, strategy_name=f"autopilot:{order.source}",
                   suggestion_id=suggestion_id)
    try:
        if live:
            from backend.engine.execution.live_order_store import LiveOrderStore
            _, status, filled = await execute_live_order(placed, ledger, adapter, LiveOrderStore(db),
                                                         placed.strategy_name, order.reason,
                                                         role="ai", owner=user_id)
            return await _record(db, user_id, order, "FILLED" if filled else "SENT", now, quiet, mode="live",
                                 price=price, broker_status=status, filled=filled)
        await fill_on_paper(ledger, placed, price, now)
    except Exception as exc:
        logger.exception("autopilot order failed for %s: %s", user_id, exc)
        return await _record(db, user_id, order, "FAILED", now, quiet, reason=str(exc), mode=mode)
    return await _record(db, user_id, order, "FILLED", now, quiet, mode="paper", price=price)


async def check_exits(db, redis, user_id: str, now: Optional[datetime] = None) -> list[dict]:
    """Sells autopilot positions opened from an engine proposal once the mark
    crosses that proposal's stop or target -- through the fence, so paper
    and live both work and the exit is logged like any other order."""
    from backend.suggestions.exits import breach

    now = now or datetime.now(timezone.utc)
    trades = [t for t in await LedgerStore(db, user_id=ledger_user(user_id)).get_trades(status="OPEN", limit=1000)
              if t.get("suggestion_id")]
    if not trades:
        return []
    suggestions = {s["id"]: s for s in await db["suggestions"].find(
        {"user_id": user_id, "id": {"$in": [t["suggestion_id"] for t in trades]}}).to_list(length=None)}
    marks = await mark_prices(db, {t["symbol"] for t in trades})
    closed = []
    for trade in trades:
        suggestion, mark = suggestions.get(trade["suggestion_id"]), marks.get(trade["symbol"])
        if suggestion is None or mark is None:
            continue
        why = breach(mark, suggestion.get("stop"), suggestion.get("target"))
        if why is None:
            continue
        result = await submit(db, redis, user_id, AutopilotOrder(
            symbol=trade["symbol"], side=Side.SELL, quantity=int(trade["quantity"]), product=_product(trade),
            source="engine", reason=f"Exit at the proposal's {why}."), now=now, suggestion_id=trade["suggestion_id"])
        if result["status"] in ("FILLED", "SENT"):
            closed.append({"symbol": trade["symbol"], "reason": why, "price": mark})
    return closed


async def disable(db, user_id: str) -> bool:
    """Turns the autopilot off; False if it already was."""
    prefs = await PrefsStore(db).get(user_id)
    if not prefs.get("autopilot_enabled"):
        return False
    await PrefsStore(db).update(user_id, {"autopilot_enabled": False})
    return True
