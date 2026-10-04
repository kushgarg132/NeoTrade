"""What the chat may do, and the one place it is done.

An action tool never executes: it checks the request, stores a PROPOSED
record in `chat_actions` and returns a card. Only `confirm` executes, after
an atomic claim (one confirm, by the owner, before expiry) and after running
every check again from the database -- never trusting the card. Execution
goes through the app's existing code: the suggestion routes, launch_run,
PrefsStore, execute_suggestion and execute_live_order.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Literal, Optional, Union

from langchain_core.tools import StructuredTool
from pymongo import ReturnDocument

from backend.core.models import Order, Side
from backend.engine.autorun import in_session
from backend.engine.execution.live_order_store import LiveOrderStore
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST
from backend.instruments.master import InstrumentMaster
from backend.prefs import PrefsStore
from backend.risk.kill_switch import KillSwitchStore
from backend.runs import RunStore
from backend.suggestions.service import execute_live_order, execute_suggestion
from backend.suggestions.store import SuggestionStore

logger = logging.getLogger(__name__)

ACTION_TTL = timedelta(minutes=5)
CARD_PREFIX = "ACTION_CARD:"
SETTINGS = {
    "daily_loss_limit": float, "per_trade_cap": float, "max_trades_per_day": int,
    "cooldown_after_losses": int, "cooldown_minutes": int,
    "auto_paper_intraday": bool, "auto_paper_longterm": bool, "guardrails_enabled": bool,
}


class ActionRefused(Exception):
    """A proposal or confirm the checks turned down; the message says why."""


# Seams the tests replace; production reads live prices, the user's broker and the clock.
async def _mark_price(symbol: str) -> float:
    from backend.routers.suggestions import _live_mark_price

    return await _live_mark_price(symbol)


async def _active_broker(user_id: str, credentials):
    """The user's own account: a card the user confirms trades there, never
    on the AI account (backend/brokers/roles.py)."""
    from backend.auth.broker_credentials import get_credential_store
    from backend.brokers.roles import RoleUnavailable, adapter_for

    try:
        return await adapter_for(user_id, "mine", credentials or get_credential_store())
    except RoleUnavailable as exc:
        raise ActionRefused(exc.reason)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _launch_run(db, user_id: str) -> str:
    from backend.routers.trading import launch_run

    prefs = await PrefsStore(db).get(user_id)
    return await launch_run(user_id, "INTRADAY", prefs["universe"], 60.0, RunStore(db), origin="chat")


async def _stop_run(db, run_id: str) -> None:
    from backend.routers.trading import stop_background_run

    await stop_background_run(run_id)
    await RunStore(db).mark_stopped(run_id)


class ChatActionStore:
    def __init__(self, db) -> None:
        self.collection = db["chat_actions"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("id", unique=True)
        await self.collection.create_index([("user_id", 1), ("status", 1)])

    async def propose(self, user_id, kind, params, summary, venue, needs_second_tap, message) -> dict:
        now = _now()
        card = {
            "id": str(uuid.uuid4()), "kind": kind, "summary": summary, "venue": venue,
            "needs_second_tap": needs_second_tap, "expires_at": (now + ACTION_TTL).isoformat(),
        }
        await self.collection.insert_one({
            **card, "user_id": user_id, "params": params, "message": message, "status": "PROPOSED",
            "result": None, "created_at": now, "expires_at": now + ACTION_TTL,
        })
        return card

    async def get(self, user_id: str, action_id: str) -> Optional[dict]:
        return await self.collection.find_one({"id": action_id, "user_id": user_id}, {"_id": 0})

    async def claim(self, user_id: str, action_id: str) -> Optional[dict]:
        doc = await self.collection.find_one_and_update(
            {"id": action_id, "user_id": user_id, "status": "PROPOSED", "expires_at": {"$gt": _now()}},
            {"$set": {"status": "CONFIRMED", "confirmed_at": _now()}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is not None:
            doc.pop("_id", None)
        return doc

    async def set_status(self, action_id: str, status: str, result=None) -> None:
        await self.collection.update_one({"id": action_id}, {"$set": {"status": status, "result": result}})

    async def cancel(self, user_id: str, action_id: str) -> bool:
        result = await self.collection.update_one(
            {"id": action_id, "user_id": user_id, "status": "PROPOSED"}, {"$set": {"status": "CANCELLED"}}
        )
        return result.modified_count == 1


# ---------------------------------------------------------------------------
# Checks, run at proposal and again at confirm.
# ---------------------------------------------------------------------------

async def _pending_suggestion(db, user_id: str, suggestion_id: str, live: bool) -> dict:
    suggestion = await SuggestionStore(db).get(user_id, suggestion_id)
    if suggestion is None or suggestion["status"] != "PENDING":
        raise ActionRefused("No such pending proposal.")
    if live and not suggestion.get("option_contract"):
        raise ActionRefused("Only option proposals can be approved live; this one can be approved on paper.")
    return suggestion


def _setting(name: str, value) -> object:
    if name not in SETTINGS:
        raise ActionRefused(f"{name} cannot be changed from chat. Allowed: {', '.join(SETTINGS)}.")
    kind = SETTINGS[name]
    if kind is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)  # the tool schema coerces a JSON 1 to 1.0
        text = str(value).strip().lower()
        if text in ("true", "on", "yes", "1"):
            return True
        if text in ("false", "off", "no", "0"):
            return False
        raise ActionRefused(f"{name} is on or off.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ActionRefused(f"{name} needs a number.")
    if number < 0 or (kind is int and number != int(number)):
        raise ActionRefused(f"{name} needs a {'whole ' if kind is int else ''}number of zero or more.")
    return int(number) if kind is int else number


async def _order_checks(db, user_id: str, params: dict, credentials) -> tuple[float, object]:
    """Returns (fresh price, live adapter or None). Raises ActionRefused."""
    symbol, quantity = params["symbol"], params["quantity"]
    if quantity <= 0:
        raise ActionRefused("Quantity must be a whole number above zero.")
    if await InstrumentMaster(db).get("NSE", symbol) is None:
        raise ActionRefused(f"{symbol} is not an NSE stock this app knows.")
    price = await _mark_price(symbol)
    cap = (await PrefsStore(db).get(user_id))["per_trade_cap"]
    if price * quantity > cap:
        raise ActionRefused(f"₹{price * quantity:,.0f} is over your per-trade cap of ₹{cap:,.0f}.")
    if params["venue"] != "live":
        return price, None
    now = _now()
    if not in_session(now):
        raise ActionRefused("The market is closed; live orders go only between 09:15 and 15:30 IST on weekdays.")
    if await KillSwitchStore(db).is_tripped(user_id, now.astimezone(IST).date()):
        raise ActionRefused("Your daily loss limit was hit today: no new live orders.")
    adapter = await _active_broker(user_id, credentials)
    if adapter is None:
        raise ActionRefused("No broker is connected. Log in to your broker in Settings first.")
    return price, adapter


# ---------------------------------------------------------------------------
# Tools: propose only.
# ---------------------------------------------------------------------------

def action_tools(db, redis, user_id: str, message: str) -> list:
    store = ChatActionStore(db)

    async def card(kind, params, summary, venue="paper", second_tap=False) -> str:
        return CARD_PREFIX + json.dumps(await store.propose(user_id, kind, params, summary, venue, second_tap, message))

    async def propose_approve(suggestion_id: str, live: bool = False) -> str:
        try:
            s = await _pending_suggestion(db, user_id, suggestion_id, live)
        except ActionRefused as exc:
            return str(exc)
        venue = "live" if live else "paper"
        return await card("approve", {"suggestion_id": suggestion_id, "live": live},
                          f"Approve {s['symbol']} · {s['side']} {s['quantity']:g} @ ₹{s.get('entry_ref') or 0:,.2f} on {venue}",
                          venue, second_tap=live)

    async def propose_decline(suggestion_id: str, reason: Optional[str] = None) -> str:
        try:
            s = await _pending_suggestion(db, user_id, suggestion_id, False)
        except ActionRefused as exc:
            return str(exc)
        return await card("decline", {"suggestion_id": suggestion_id, "reason": reason},
                          f"Decline {s['symbol']} · {s['side']} {s['quantity']:g}" + (f" — {reason}" if reason else ""))

    async def propose_paper_run(action: Literal["start", "stop"]) -> str:
        active = [r for r in await RunStore(db).list_active(user_id) if r["mode"] == "INTRADAY"]
        if action == "start" and active:
            return "An intraday paper run is already running."
        if action == "stop" and not active:
            return "No intraday paper run is running."
        return await card("paper_run", {"action": action},
                          "Start an intraday paper run now" if action == "start" else "Stop today's intraday paper run")

    async def propose_setting(name: str, value: Union[float, bool, str]) -> str:
        try:
            parsed = _setting(name, value)
        except ActionRefused as exc:
            return str(exc)
        current = (await PrefsStore(db).get(user_id)).get(name)
        return await card("setting", {"name": name, "value": parsed},
                          f"Set {name.replace('_', ' ')} to {parsed} (now {current})")

    async def propose_order(
        symbol: str, side: Literal["BUY", "SELL"], quantity: int,
        product: Literal["CNC", "MIS"] = "CNC", venue: Literal["paper", "live"] = "paper",
        account: Literal["mine", "ai"] = "mine",
    ) -> str:
        params = {"symbol": symbol.strip().upper().removesuffix(".NS"), "side": side, "quantity": quantity,
                  "product": product, "venue": venue}
        if account == "ai":
            # The AI account is the autopilot's: no card -- it goes through the
            # fence and runs (or is refused) now (backend/autopilot/). The venue
            # must match its mode, so "paper" can never become a real order.
            from backend.autopilot.service import AutopilotOrder, submit

            live_mode = bool((await PrefsStore(db).get(user_id)).get("autopilot_live"))
            if (venue == "live") != live_mode:
                return (f"The AI account's autopilot is in {'live' if live_mode else 'paper'} mode; "
                        f"use venue='{'live' if live_mode else 'paper'}' for it.")

            result = await submit(db, redis, user_id, AutopilotOrder(
                symbol=params["symbol"], side=Side(side), quantity=int(quantity), product=product,
                source="chat", reason=f"From chat: {message[:160]}"))
            if result["status"] in ("FILLED", "SENT"):
                verb = "bought" if side == "BUY" else "sold"
                return (f"Autopilot {verb} {quantity} {params['symbol']} on the AI account "
                        f"({result.get('mode')}) at ₹{result.get('price', 0):,.2f}.")
            return f"The autopilot did not place it: {result.get('reason')}"
        try:
            price, _ = await _order_checks(db, user_id, params, None)
        except ActionRefused as exc:
            return str(exc)
        kind = "delivery" if product == "CNC" else "intraday"
        return await card("order", params,
                          f"{side} {quantity} {params['symbol']} · {kind} · market · ~₹{price * quantity:,.0f} on {venue}",
                          venue, second_tap=venue == "live")

    async def propose_memory(facts: list[str]) -> str:
        from backend.profile.models import MAX_MEMORIES, MAX_MEMORY_CHARS
        from backend.profile.store import ProfileStore, _norm

        saved = {_norm(m["text"]) for m in (await ProfileStore(db).get(user_id))["memories"]}
        new: list[str] = []
        for fact in facts or []:
            text = " ".join((fact or "").split())
            if len(text) > MAX_MEMORY_CHARS:
                return f"A memory can be at most {MAX_MEMORY_CHARS} characters; shorten: {text[:40]}…"
            if text and _norm(text) not in saved and _norm(text) not in {_norm(n) for n in new}:
                new.append(text)
        if not new:
            return "That is already in the trader's profile memory." if facts else "There is nothing to remember."
        if len(saved) + len(new) > MAX_MEMORIES:
            return f"The profile memory is full ({MAX_MEMORIES}); the trader can delete some on the Profile page."
        summary = f"Remember: {new[0]}" if len(new) == 1 else "Remember:\n" + "\n".join(f"• {t}" for t in new)
        return await card("memory", {"facts": new}, summary)

    async def _mine_card(build) -> str:
        """A card on the user's own account; a refusal comes back as text."""
        from backend.chat import account_actions as aa

        try:
            kind, params, summary = await build(await aa.mine_adapter(user_id, None))
        except (aa._Refused, ActionRefused) as exc:
            return str(exc)
        return await card(kind, params, summary, venue="live", second_tap=True)

    async def propose_exit(symbol: str, quantity: Optional[int] = None) -> str:
        from backend.chat import account_actions as aa
        return await _mine_card(lambda adapter: aa.propose_exit(adapter, symbol, quantity))

    async def propose_cancel_order(order_id: str) -> str:
        from backend.chat import account_actions as aa
        return await _mine_card(lambda adapter: aa.propose_cancel(adapter, order_id))

    async def propose_modify_order(order_id: str, price: Optional[float] = None, quantity: Optional[int] = None) -> str:
        from backend.chat import account_actions as aa
        return await _mine_card(lambda adapter: aa.propose_modify(adapter, order_id, price, quantity))

    async def propose_stop_loss(symbol: str, trigger_price: float) -> str:
        from backend.chat import account_actions as aa
        last = await _mark_price(symbol.strip().upper().removesuffix(".NS"))
        return await _mine_card(lambda adapter: aa.propose_stop(adapter, symbol, trigger_price, last))

    def tool(fn, description):
        return StructuredTool.from_function(coroutine=fn, name=fn.__name__, description=description)

    note = " Only prepares a card; the user must tap Confirm before anything happens."
    return [
        tool(propose_approve, "Approve a pending proposal by its id (from get_decisions); live=true only for option proposals." + note),
        tool(propose_decline, "Decline a pending proposal by its id, with an optional reason." + note),
        tool(propose_paper_run, "Start or stop the user's intraday paper-trading run." + note),
        tool(propose_setting, "Change one of the user's limits or switches: " + ", ".join(SETTINGS) + "." + note),
        tool(propose_order, "Place a market order for an NSE stock: side BUY or SELL, whole quantity, product CNC "
                            "(delivery) or MIS (intraday), venue paper or live. Live is real money. account mine "
                            "(default; a card the trader confirms) or ai (the AI account: the autopilot runs it "
                            "at once within its limits, no card)." + note),
        tool(propose_exit, "Sell all (default) or part of a holding in the trader's OWN account at market." + note),
        tool(propose_cancel_order, "Cancel an open order in the trader's own account, by its broker order id." + note),
        tool(propose_modify_order, "Change the price and/or quantity of an open order in the trader's own account." + note),
        tool(propose_stop_loss, "Add a stop-loss (SL-M) below the price on a holding in the trader's own account." + note),
        tool(propose_memory, "Save lasting facts or preferences the trader shared (goals, situation, dislikes) "
                             "to their profile memory -- pass ALL of them in one call, as one card." + note),
    ]


# ---------------------------------------------------------------------------
# Confirm: the only place an action runs.
# ---------------------------------------------------------------------------

async def confirm(db, redis, credentials, user_id: str, action_id: str, second_tap: bool = False) -> dict:
    store = ChatActionStore(db)
    action = await store.claim(user_id, action_id)
    if action is None:
        existing = await store.get(user_id, action_id)
        if existing is None:
            raise ActionRefused("No such action.")
        if existing["status"] == "PROPOSED":
            await store.set_status(action_id, "EXPIRED")
            raise ActionRefused("This card expired. Ask again for a fresh one.")
        raise ActionRefused(f"This action is already {existing['status'].lower()}.")

    if action["needs_second_tap"] and not second_tap:
        await store.set_status(action_id, "PROPOSED")
        return {"status": "NEEDS_SECOND_TAP", "result": "Real money. Tap Confirm again to send it."}

    try:
        result = await _execute(db, credentials, user_id, action)
    except ActionRefused as exc:
        await store.set_status(action_id, "FAILED", str(exc))
        raise
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("chat action %s (%s) failed: %s", action_id, action["kind"], detail)
        await store.set_status(action_id, "FAILED", str(detail))
        raise ActionRefused(str(detail))
    await store.set_status(action_id, "CONFIRMED", result)
    return {"status": "CONFIRMED", "result": result}


async def _execute(db, credentials, user_id: str, action: dict) -> str:
    from backend.ws.publish import publisher_for

    kind, params = action["kind"], action["params"]
    ledger = LedgerStore(db, user_id=user_id, on_change=publisher_for(user_id))

    if kind in ("approve", "decline"):
        await _pending_suggestion(db, user_id, params["suggestion_id"], params.get("live", False))
        from backend.routers import suggestions as routes

        user = SimpleNamespace(id=user_id)
        store = SuggestionStore(db)
        if kind == "decline":
            await routes.reject_suggestion(
                params["suggestion_id"], routes.RejectRequest(reason=params.get("reason")), user=user, store=store,
            )
            return "Declined."
        if params.get("live"):
            done = await routes.approve_suggestion_live(
                params["suggestion_id"], user=user, store=store, ledger=ledger, options_broker=routes._options_broker,
            )
        else:
            done = await routes.approve_suggestion(
                params["suggestion_id"], user=user, store=store, ledger=ledger,
                mark_price=_mark_price, option_premium=routes._live_option_premium,
            )
        return f"{done['symbol']}: {done['status'].lower()}" + (f" ({done['reason']})" if done.get("reason") else "")

    if kind == "paper_run":
        active = [r for r in await RunStore(db).list_active(user_id) if r["mode"] == "INTRADAY"]
        if params["action"] == "start":
            if active:
                raise ActionRefused("An intraday paper run is already running.")
            return f"Started paper run {await _launch_run(db, user_id)}."
        if not active:
            raise ActionRefused("No intraday paper run is running.")
        for run in active:
            await _stop_run(db, run["run_id"])
        return "Stopped the intraday paper run."

    if kind == "memory":
        from backend.profile.models import MemoryRefused
        from backend.profile.store import ProfileStore

        saved = 0
        for fact in params.get("facts") or [params["text"]]:  # "text": cards made before batching
            try:
                await ProfileStore(db).add_memory(user_id, fact, "chat")
                saved += 1
            except MemoryRefused as exc:
                if "full" in str(exc):
                    raise ActionRefused(str(exc))
        return "Saved to your profile memory." if saved == 1 else f"Saved {saved} things to your profile memory."

    if kind == "setting":
        value = _setting(params["name"], params["value"])
        await PrefsStore(db).update(user_id, {params["name"]: value})
        return f"{params['name'].replace('_', ' ')} is now {value}."

    if kind == "order":
        price, adapter = await _order_checks(db, user_id, params, credentials)
        product, side = params["product"], params["side"]
        if adapter is None:
            order = await execute_suggestion(
                {"symbol": params["symbol"], "side": side, "quantity": params["quantity"],
                 "mode": "INTRADAY" if product == "MIS" else "LONGTERM"},
                ledger, price, strategy_name="chat",
            )
            return f"Paper {side} {params['quantity']} {params['symbol']} filled at ₹{price:,.2f}."
        order = Order(id=str(uuid.uuid4()), symbol=params["symbol"], side=Side(side), quantity=params["quantity"],
                      order_type="MARKET", product=product, strategy_name="chat")
        _, status, filled = await execute_live_order(order, ledger, adapter, LiveOrderStore(db), "chat", action["message"])
        return f"Sent to your broker: {status.lower()}, {filled:g} of {params['quantity']} filled."

    if kind in ("exit", "cancel_order", "modify_order", "stop_loss"):
        # The user's own account only (backend/chat/account_actions.py).
        from backend.chat import account_actions as aa

        if not in_session(_now()):
            raise ActionRefused("The market is closed; orders go only between 09:15 and 15:30 IST on weekdays.")
        adapter = await aa.mine_adapter(user_id, credentials)
        try:
            return await aa.execute(adapter, kind, params)
        except aa._Refused as exc:
            raise ActionRefused(str(exc))

    raise ActionRefused(f"Unknown action {kind!r}.")
