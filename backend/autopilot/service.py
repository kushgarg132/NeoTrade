"""Runs an autopilot order: fence -> paper fill (or, in live mode, the AI
account's broker) -> log -> Telegram note with a one-tap stop."""

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


@dataclass
class AutopilotOrder:
    symbol: str
    side: Side
    quantity: int
    product: Literal["CNC", "MIS"]
    source: Literal["chat", "engine", "factor"]
    reason: str


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
    ledger = LedgerStore(db, user_id=user_id)
    mine = [t for t in await ledger.get_trades(limit=1000, venue=venue)
            if str(t.get("strategy") or "").startswith("autopilot:")]
    open_trades = [t for t in mine if t.get("status") == "OPEN"]
    marks = await mark_prices(db, {t["symbol"] for t in open_trades}) if open_trades else {}
    deployed = sum(t["quantity"] * marks.get(t["symbol"], t.get("entry_price") or 0) for t in open_trades)
    unrealized = sum((marks.get(t["symbol"], t.get("entry_price") or 0) - (t.get("entry_price") or 0)) * t["quantity"]
                     for t in open_trades)
    realized = sum(t.get("realized_pnl") or 0 for t in mine
                   if t.get("status") == "CLOSED" and (_aware(t.get("exit_at")) or day_start) >= day_start)
    entries = await db["autopilot_log"].count_documents(
        {"user_id": user_id, "status": "FILLED", "side": "BUY", "at": {"$gte": day_start}})
    state = await db["autopilot_state"].find_one({"_id": user_id}) or {}
    tripped = state.get("tripped_day") == day.isoformat()
    if not tripped and realized + unrealized <= -prefs["autopilot_daily_loss_limit"]:
        tripped = True
        await db["autopilot_state"].update_one({"_id": user_id}, {"$set": {"tripped_day": day.isoformat(),
                                                                          "user_id": user_id}}, upsert=True)
    tripped = tripped or bool(await KillSwitchStore(db).is_tripped(user_id, day))
    return fence.FenceState(deployed=deployed, entries_today=entries, open_symbols={t["symbol"] for t in open_trades},
                            kill_tripped=tripped, session_ok=in_session(now))


async def _record(db, user_id: str, order: AutopilotOrder, status: str, now: datetime, **extra) -> dict:
    row = {"user_id": user_id, "at": now, "status": status, **asdict(order), "side": order.side.value, **extra}
    await db["autopilot_log"].insert_one(dict(row))
    verb = "bought" if order.side == Side.BUY else "sold"
    if status == "FILLED":
        text = (f"🤖 AI {verb} {order.quantity} {order.symbol} on the AI account"
                f"{' (paper)' if extra.get('mode') == 'paper' else ''} at ₹{extra.get('price', 0):,.2f}.\n{order.reason}")
    else:
        text = f"🤖 Autopilot refused {order.side.value} {order.quantity} {order.symbol}: {extra.get('reason')}"
    await _notify(db, user_id, text)
    return {"status": status, **extra}


async def submit(db, redis, user_id: str, order: AutopilotOrder, now: Optional[datetime] = None) -> dict:
    from backend.suggestions.service import execute_live_order, fill_on_paper

    now = now or datetime.now(timezone.utc)
    prefs = await PrefsStore(db).get(user_id)
    live = bool(prefs.get("autopilot_live"))
    price = (await mark_prices(db, {order.symbol})).get(order.symbol)
    if not price:
        return await _record(db, user_id, order, "REFUSED", now, reason=f"No live price for {order.symbol}.")
    reason = fence.check(order, price, await _state(db, user_id, prefs, "live" if live else "paper", now), prefs)
    adapter = None
    if reason is None and live:
        from backend.auth.broker_credentials import get_credential_store
        try:
            adapter = await adapter_for(user_id, "ai", get_credential_store(), redis)
        except RoleUnavailable as exc:
            reason = exc.reason
    if reason:
        return await _record(db, user_id, order, "REFUSED", now, reason=reason, mode="live" if live else "paper")

    ledger = LedgerStore(db, user_id=user_id)
    placed = Order(id=str(uuid.uuid4()), symbol=order.symbol, side=order.side, quantity=order.quantity,
                   order_type="MARKET", product=order.product, strategy_name=f"autopilot:{order.source}")
    try:
        if live:
            from backend.engine.execution.live_order_store import LiveOrderStore
            _, status, filled = await execute_live_order(placed, ledger, adapter, LiveOrderStore(db),
                                                         placed.strategy_name, order.reason)
            return await _record(db, user_id, order, "FILLED" if filled else "SENT", now, mode="live",
                                 price=price, broker_status=status, filled=filled)
        await fill_on_paper(ledger, placed, price, now)
    except Exception as exc:
        logger.exception("autopilot order failed for %s: %s", user_id, exc)
        return await _record(db, user_id, order, "FAILED", now, reason=str(exc), mode="live" if live else "paper")
    return await _record(db, user_id, order, "FILLED", now, mode="paper", price=price)


async def disable(db, user_id: str) -> bool:
    """Turns the autopilot off; False if it already was."""
    prefs = await PrefsStore(db).get(user_id)
    if not prefs.get("autopilot_enabled"):
        return False
    await PrefsStore(db).update(user_id, {"autopilot_enabled": False})
    return True
