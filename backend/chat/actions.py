"""What the chat may do, and the one place it is done.

An action tool never executes: it checks the request, stores a PROPOSED
record in `chat_actions` and returns a card. Only `confirm` executes, after
an atomic claim (one confirm, by the owner, before expiry) and after running
every check again from the database -- never trusting the card. Execution
goes through the app's existing code: the suggestion routes, launch_run,
PrefsStore and execute_live_order.
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
from backend.engine.persistence import LedgerStore, mine_book
from backend.engine.session import IST
from backend.instruments.master import InstrumentMaster
from backend.prefs import PrefsStore
from backend.risk import live_confirm
from backend.risk.kill_switch import KillSwitchStore
from backend.runs import RunStore
from backend.suggestions.service import execute_live_order
from backend.suggestions.store import SuggestionStore

logger = logging.getLogger(__name__)

ACTION_TTL = timedelta(minutes=5)
CARD_PREFIX = "ACTION_CARD:"
PAPER_ORDERS_GONE = ("There are no paper orders on your account any more. Trade it for real (venue live), "
                     "or name the AI account (account ai) to have its autopilot trade.")
PAPER_APPROVALS_GONE = ("There is no paper approval any more: the AI account paper-trades proposals itself. "
                        "Approve with real money on your account, or decline.")
SETTINGS = {
    "daily_loss_limit": float, "per_trade_cap": float, "max_trades_per_day": int,
    "cooldown_after_losses": int, "cooldown_minutes": int, "no_buy_before_results_days": int,
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

    async def pending(self, user_id: str) -> list[dict]:
        cursor = self.collection.find(
            {"user_id": user_id, "status": "PROPOSED", "expires_at": {"$gt": _now()}},
            {"_id": 0, "id": 1, "kind": 1, "summary": 1, "venue": 1, "needs_second_tap": 1, "expires_at": 1},
        ).sort("created_at", -1)
        return await cursor.to_list(length=50)

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
    from backend.suggestions.notify import is_admin

    if not await is_admin(db, user_id):  # engine ideas are admin-only advice
        raise ActionRefused("Engine ideas are not available on this account.")
    suggestion = await SuggestionStore(db).get(user_id, suggestion_id)
    if suggestion is None or suggestion["status"] != "PENDING":
        raise ActionRefused("No such pending proposal.")
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
    limit = params.get("limit_price") if params.get("order_type", "MARKET") == "LIMIT" else None
    if params.get("order_type", "MARKET") == "LIMIT":
        if not limit or limit <= 0 or abs(limit - price) > 0.2 * price:
            raise ActionRefused(
                f"Limit ₹{limit or 0:,.2f} is more than 20% from the price ₹{price:,.2f}; check the number."
            )
    basis = limit or price
    cap = (await PrefsStore(db).get(user_id))["per_trade_cap"]
    if basis * quantity > cap:
        raise ActionRefused(f"₹{basis * quantity:,.0f} is over your per-trade cap of ₹{cap:,.0f}.")
    delivery_sell = params["side"] == "SELL" and params.get("product", "CNC") == "CNC"
    if params["venue"] != "live":
        raise ActionRefused(PAPER_ORDERS_GONE)
    now = _now()
    if not in_session(now):
        raise ActionRefused("The market is closed; live orders go only between 9:15 AM and 3:30 PM IST on weekdays.")
    if await KillSwitchStore(db).is_tripped(user_id, now.astimezone(IST).date()):
        raise ActionRefused("Your daily loss limit was hit today: no new live orders.")
    if params["side"] == "BUY":
        from backend.mine.events import buy_blocked

        why = await buy_blocked(db, await PrefsStore(db).get(user_id), symbol, now.astimezone(IST).date())
        if why:
            raise ActionRefused(why)
    adapter = await _active_broker(user_id, credentials)
    if adapter is None:
        raise ActionRefused("No broker is connected. Log in to your broker in Settings first.")
    if params.get("order_type") == "LIMIT" and not getattr(adapter, "SUPPORTS_LIMIT", False):
        # Only adapters that send the limit price may take one; another would
        # turn it into a market order (or reject it).
        raise ActionRefused("Your broker does not take limit orders here; place a market order.")
    if delivery_sell:
        from backend.chat.account_actions import _held

        _refuse_oversell(symbol, quantity, (await _held(adapter, symbol))[0])
    return price, adapter


async def _modify_checks(db, user_id: str, adapter, params: dict) -> None:
    """A modify is held to the same limits as a new order: whole quantity and
    price above 0, the per-trade cap on the new notional, and no extra shares
    on a day the kill switch tripped. It used to check only that the order
    was still open."""
    from backend.chat.account_actions import _open_order

    quantity, price = params.get("quantity"), params.get("price")
    if quantity is not None and (quantity <= 0 or quantity != int(quantity)):
        raise ActionRefused("Quantity must be a whole number above zero.")
    if price is not None and price <= 0:
        raise ActionRefused("The new price must be a price above 0.")
    order = await _open_order(adapter, params["order_id"])
    if order is None:
        raise ActionRefused(f"There is no open order {params['order_id']} in your account.")
    new_qty = quantity if quantity is not None else float(order["quantity"])
    unit = price or float(order.get("price") or 0) or await _mark_price(order["symbol"])
    cap = (await PrefsStore(db).get(user_id))["per_trade_cap"]
    if new_qty * unit > cap:
        raise ActionRefused(f"₹{new_qty * unit:,.0f} is over your per-trade cap of ₹{cap:,.0f}.")
    if new_qty > float(order["quantity"]) and await KillSwitchStore(db).is_tripped(
        user_id, _now().astimezone(IST).date()
    ):
        raise ActionRefused("Your daily loss limit was hit today: no extra shares on an open order.")


def _refuse_oversell(symbol: str, quantity: int, held: int) -> None:
    if quantity > held:
        raise ActionRefused(f"You hold {held} {symbol}; a delivery sell can't be more than that.")


# ---------------------------------------------------------------------------
# Tools: propose only.
# ---------------------------------------------------------------------------

def _strategy_vocabulary() -> str:
    from backend.builder.draft import _vocabulary

    return "INTRADAY blocks:\n" + _vocabulary() + "\nSWING blocks (daily bars):\n" + _vocabulary("swing")


def action_tools(db, redis, user_id: str, message: str) -> list:
    store = ChatActionStore(db)

    # venue only on cards that trade: a decline or a setting is neither paper nor live.
    async def card(kind, params, summary, venue=None, second_tap=False) -> str:
        return CARD_PREFIX + json.dumps(await store.propose(user_id, kind, params, summary, venue, second_tap, message))

    async def propose_approve(suggestion_id: str, live: bool = False) -> str:
        if not live:
            return PAPER_APPROVALS_GONE
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
                          "Start an intraday paper run now" if action == "start" else "Stop today's intraday paper run",
                          venue="paper")

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
        product: Literal["CNC", "MIS"] = "CNC", venue: Optional[Literal["paper", "live"]] = None,
        account: Literal["mine", "ai"] = "mine",
    ) -> str:
        # Unnamed venue: real money on the user's own account (still two taps);
        # on the AI account, paper -- real money there must be named.
        live_mode = bool((await PrefsStore(db).get(user_id)).get("autopilot_live"))
        venue = venue or ("live" if account == "mine" else "paper")
        params = {"symbol": symbol.strip().upper().removesuffix(".NS"), "side": side, "quantity": quantity,
                  "product": product, "venue": venue}
        if account == "ai":
            # The AI account is the autopilot's: the order goes through its
            # fence at confirm. Still a card: the agent also reads news and
            # stock text, and that text must never place an order on its own
            # (prompt injection). The venue must match the autopilot's mode,
            # so "paper" can never become a real order.
            if (venue == "live") != live_mode:
                return (f"The AI account's autopilot is in {'live' if live_mode else 'paper'} mode; "
                        f"use venue='{'live' if live_mode else 'paper'}' for it.")
            return await card("ai_order", params,
                              f"AI account: {side} {quantity} {params['symbol']} · {'delivery' if product == 'CNC' else 'intraday'}"
                              f" · {'real money' if venue == 'live' else 'paper'}",
                              venue, second_tap=venue == "live")
        try:
            price, _ = await _order_checks(db, user_id, params, None)
        except ActionRefused as exc:
            return str(exc)
        kind = "delivery" if product == "CNC" else "intraday"
        return await card("order", params,
                          f"{side} {quantity} {params['symbol']} · {kind} · market · ~₹{price * quantity:,.0f} on {venue}",
                          venue, second_tap=venue == "live")

    async def propose_strategy(name: str, thesis: str, spec: dict) -> str:
        from backend.builder import store as built
        from backend.builder.validate import describe, validate_spec

        name = (name or "").strip()
        if not 1 <= len(name) <= 40:
            return "Give the strategy a name of 1 to 40 characters."
        if len(thesis or "") > 200:
            return "Keep the thesis under 200 characters."
        mine = [d for d in await built.visible(db, user_id) if d.get("owner_id") == user_id]
        clean, reason = validate_spec(spec, mine)
        if clean is None:
            return f"Refused: {reason}. Fix the spec and propose it again."
        return await card("strategy", {"name": name, "thesis": thesis or "", "spec": clean},
                          f"Create and test strategy ‘{name}’: {describe(clean)}")

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
        async def build(adapter):
            kind, params, summary = await aa.propose_modify(adapter, order_id, price, quantity)
            await _modify_checks(db, user_id, adapter, params)
            return kind, params, summary

        return await _mine_card(build)

    async def propose_stop_loss(symbol: str, trigger_price: float) -> str:
        from backend.chat import account_actions as aa
        last = await _mark_price(symbol.strip().upper().removesuffix(".NS"))
        return await _mine_card(lambda adapter: aa.propose_stop(adapter, symbol, trigger_price, last))

    def tool(fn, description):
        return StructuredTool.from_function(coroutine=fn, name=fn.__name__, description=description)

    note = " Only prepares a card; the user must tap Confirm before anything happens."
    return [
        tool(propose_approve, "Approve a pending proposal by its id (from get_decisions) with real money on the trader's own account (live=true). There is no paper approval: the AI account paper-trades proposals itself." + note),
        tool(propose_decline, "Decline a pending proposal by its id, with an optional reason." + note),
        tool(propose_paper_run, "Start or stop the user's intraday paper-trading run." + note),
        tool(propose_setting, "Change one of the user's limits or switches: " + ", ".join(SETTINGS) + "." + note),
        tool(propose_order, "Place a market order for an NSE stock: side BUY or SELL, whole quantity, product CNC "
                            "(delivery) or MIS (intraday). account mine (default): real money on the trader's own account, "
                            "venue live, a card the trader confirms twice. account ai: the AI account, venue matching "
                            "its autopilot mode (paper or live); a card the trader confirms, then the autopilot runs it within its limits." + note),
        tool(propose_exit, "Sell all (default) or part of a holding in the trader's OWN account at market." + note),
        tool(propose_cancel_order, "Cancel an open order in the trader's own account, by its broker order id." + note),
        tool(propose_modify_order, "Change the price and/or quantity of an open order in the trader's own account." + note),
        tool(propose_stop_loss, "Add a stop-loss (SL-M) below the price on a holding in the trader's own account." + note),
        tool(propose_strategy, "Create the trader's own private strategy from rule blocks; on confirm it is "
                               "backtested and trades on paper only if it passes (intraday: a year of 5-minute "
                               "history, ~10 min; swing: 3 years of daily bars, seconds). Swing specs need "
                               "\"horizon\": \"swing\", are long only, and need \"max_hold_days\": {\"days\": n} "
                               "and optionally \"trail_atr\": {\"multiple\": x}; their stop is {\"atr_multiple\": x} or "
                               "{\"swing_low\": true}. Intraday spec = {\"setup\": {<one setup>: {params}}, \"filters\": {<0-3 filters>: "
                               "{params}}, \"side\": \"long\"|\"short\", \"stop\": {\"atr_multiple\": x} or "
                               "{\"setup_bar\": true}, \"target\": {\"r_multiple\": x}}. Blocks and ranges:\n"
                               + _strategy_vocabulary() + "\n" + note),
        tool(propose_memory, "Save lasting facts or preferences the trader shared (goals, situation, dislikes) "
                             "to their profile memory -- pass ALL of them in one call, as one card." + note),
    ]


# ---------------------------------------------------------------------------
# Confirm: the only place an action runs.
# ---------------------------------------------------------------------------

async def confirm(db, redis, credentials, user_id: str, action_id: str, confirm_token: Optional[str] = None) -> dict:
    """A real-money card runs in two calls: the first returns NEEDS_SECOND_TAP
    and a `confirm_token` (backend/risk/live_confirm.py), the second must
    present it. Anything wrong with the token: the card stays PROPOSED and
    TokenRefused is raised before any check or order."""
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

    if action["needs_second_tap"]:
        subject = f"action:{action_id}"
        if not confirm_token:
            await store.set_status(action_id, "PROPOSED")
            token = await live_confirm.issue(redis, user_id, subject, action["params"])
            return {"status": "NEEDS_SECOND_TAP", "result": "Real money. Tap Confirm again to send it.",
                    "confirm_token": token, "expires_in": live_confirm.TTL_SECONDS}
        try:
            await live_confirm.redeem(redis, user_id, subject, action["params"], confirm_token)
        except live_confirm.TokenRefused:
            await store.set_status(action_id, "PROPOSED")
            raise

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
    # Approvals and orders here are real orders on the user's own account.
    ledger = LedgerStore(db, user_id=mine_book(user_id), on_change=publisher_for(user_id))

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
        if not params.get("live"):
            raise ActionRefused(PAPER_APPROVALS_GONE)
        # The card's own token was just spent: place it (every check runs again there).
        done = await routes.place_live_approval(
            params["suggestion_id"], user=user, store=store, ledger=ledger, options_broker=routes._options_broker,
            mine_broker=routes._mine_broker, mark_price=_mark_price,
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

    if kind == "strategy":
        from backend.routers import settings as routes

        # The form's own handler: it re-validates the stored spec and applies every limit.
        doc = await routes.submit_strategy(routes.StrategyBody(**params), user=SimpleNamespace(id=user_id))
        return f"Testing ‘{doc['name']}’ now (about 10 minutes); see AI › Strategies › Mine."

    if kind == "setting":
        value = _setting(params["name"], params["value"])
        await PrefsStore(db).update(user_id, {params["name"]: value})
        return f"{params['name'].replace('_', ' ')} is now {value}."

    if kind == "ai_order":
        from backend.autopilot.service import AutopilotOrder, submit
        from backend.database import db as handle

        if (params["venue"] == "live") != bool((await PrefsStore(db).get(user_id)).get("autopilot_live")):
            raise ActionRefused("The autopilot's mode changed since this card was made; ask again.")
        result = await submit(db, handle.redis, user_id, AutopilotOrder(
            symbol=params["symbol"], side=Side(params["side"]), quantity=int(params["quantity"]),
            product=params["product"], source="chat", reason=f"From chat: {action['message'][:160]}"))
        if result["status"] not in ("FILLED", "SENT"):
            raise ActionRefused(f"The autopilot did not place it: {result.get('reason')}")
        verb = "bought" if params["side"] == "BUY" else "sold"
        return (f"Autopilot {verb} {params['quantity']} {params['symbol']} on the AI account "
                f"({result.get('mode')}) at ₹{result.get('price', 0):,.2f}.")

    if kind == "order":
        price, adapter = await _order_checks(db, user_id, params, credentials)
        product, side = params["product"], params["side"]
        order_type = params.get("order_type", "MARKET")
        order = Order(id=str(uuid.uuid4()), symbol=params["symbol"], side=Side(side), quantity=params["quantity"],
                      order_type=order_type, limit_price=params.get("limit_price"), product=product,
                      strategy_name="chat")
        _, status, filled = await execute_live_order(order, ledger, adapter, LiveOrderStore(db), "chat", action["message"])
        if order_type == "LIMIT" and status in ("REJECTED", "CANCELLED"):
            return (f"Your broker {status.lower()} the limit order; {filled:g} of "
                    f"{params['quantity']} filled.")
        if order_type == "LIMIT" and status != "FILLED":
            return (f"Resting at your broker: limit ₹{params['limit_price']:,.2f}, {filled:g} of "
                    f"{params['quantity']} filled. It lasts until 3:30 PM.")
        return f"Sent to your broker: {status.lower()}, {filled:g} of {params['quantity']} filled."

    if kind in ("exit", "cancel_order", "modify_order", "stop_loss"):
        # The user's own account only (backend/chat/account_actions.py).
        from backend.chat import account_actions as aa

        if not in_session(_now()):
            raise ActionRefused("The market is closed; orders go only between 9:15 AM and 3:30 PM IST on weekdays.")
        adapter = await aa.mine_adapter(user_id, credentials)
        if kind == "modify_order":
            await _modify_checks(db, user_id, adapter, params)  # again at confirm, from the account
        try:
            return await aa.execute(adapter, kind, params)
        except aa._Refused as exc:
            raise ActionRefused(str(exc))

    raise ActionRefused(f"Unknown action {kind!r}.")
