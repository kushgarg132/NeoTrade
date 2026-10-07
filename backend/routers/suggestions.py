"""/suggestions/* -- the approve/reject inbox for AI trade proposals.

Long-term signals never execute themselves (see backend/suggestions/sink.py);
they land here carrying the sizing, stop, target, reason codes and score the
engine computed, and wait for a decision. Approving is the only place in the
app where a person causes a trade.
"""

import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.data.providers.yfinance_provider import YFinanceProvider
from backend.engine.persistence import LedgerStore
from backend.ws.publish import publisher_for
from backend.auth.broker_credentials import get_credential_store
from backend.instruments.master import InstrumentMaster
from backend.options.premiums import live_premium_source
from backend.prefs import PrefsStore
from backend.rate_limit import allow
from backend.suggestions.scan import scan_universe
from backend.brokers.protocol import BrokerSessionState
from backend.core.models import Order, Side
from backend.brokers.registry import BROKERS, get_broker_adapter
from backend.engine.execution.live_order_store import LiveOrderStore
from backend.engine.session import IST
from backend.risk.kill_switch import KillSwitchStore
from backend.suggestions.service import execute_option_suggestion_live, execute_suggestion
from backend.suggestions.store import SuggestionStore
from backend.suggestions.thesis import attach_theses

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/suggestions", tags=["Suggestions"])


def get_suggestion_store() -> SuggestionStore:
    return SuggestionStore(db.db)


def get_ledger_store(user: User = Depends(get_current_user)) -> LedgerStore:
    return LedgerStore(db.db, user_id=user.id, on_change=publisher_for(user.id))


async def _live_mark_price(symbol: str) -> float:
    instrument = await InstrumentMaster(db.db).get("NSE", symbol)
    if instrument is None:
        raise HTTPException(status_code=400, detail=f"Unknown instrument {symbol!r}")
    quote = await YFinanceProvider().quote(instrument)
    price = quote.get("last_price")
    if not price:
        raise HTTPException(status_code=503, detail=f"No live price for {symbol!r}")
    return float(price)


def get_mark_price():
    """Injected so tests can approve a suggestion without a yfinance call."""
    return _live_mark_price


async def _live_option_premium(user_id: str, symbol: str) -> float:
    """An option proposal fills at the contract's live premium from the
    user's own broker. Its symbol is an NFO contract, so the equity mark
    above cannot price it (it used to answer "Unknown instrument")."""
    contract = await InstrumentMaster(db.db).get("NFO", symbol)
    if contract is None:
        raise HTTPException(status_code=400, detail=f"Unknown option contract {symbol!r}")
    source = await live_premium_source(db.db, user_id, get_credential_store(), db.redis)
    premium = await source(contract) if source is not None else None
    if not premium:
        raise HTTPException(
            status_code=409,
            detail="Connect Kite or Upstox in Settings to fill this option at its live premium.",
        )
    return float(premium)


def get_option_premium():
    """Injected so tests can approve an option proposal without a broker."""
    return _live_option_premium


class RejectRequest(BaseModel):
    reason: Optional[str] = None


class ScanRequest(BaseModel):
    universe: Optional[list[str]] = Field(None, max_length=300)  # defaults to the user's saved universe


@router.post("/scan", status_code=202)
async def scan_now(
    body: ScanRequest = ScanRequest(),
    user: User = Depends(get_current_user),
):
    """Runs in the background: a scan pulls a year of daily history per
    symbol, which is minutes for a full universe -- far too long to hold an
    HTTP request open. New suggestions appear in the inbox as they land."""
    # Each scan is minutes of background work: a few per 10 minutes is plenty.
    if not await allow(db.redis, f"scan:{user.id}", limit=5, window_seconds=600):
        raise HTTPException(status_code=429, detail="Too many scans started; wait a few minutes and try again.")
    prefs = await PrefsStore(db.db).get(user.id)
    universe = body.universe or prefs["universe"]

    asyncio.create_task(_scan_and_enrich(user.id, universe, prefs))
    return {"started": True, "symbols": len(universe)}


async def _scan_and_enrich(user_id: str, universe: list[str], prefs: dict) -> None:
    try:
        created = await scan_universe(
            db.db, user_id=user_id, universe=universe,
            account_size=prefs["account_size"], max_exposure=prefs["max_exposure"],
            source="manual", redis=db.redis,
        )
        if created:
            await attach_theses(db.db, user_id, created)
    except Exception as exc:
        logger.exception("manual scan failed for %s: %s", user_id, exc)


@router.get("")
async def list_suggestions(
    mode: Optional[Literal["INTRADAY", "LONGTERM"]] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    store: SuggestionStore = Depends(get_suggestion_store),
):
    return await store.list(user.id, mode=mode, status=status, limit=limit)


def _require_strategy(suggestion: dict) -> None:
    """A fill no strategy owns can never be judged: approving one is refused."""
    if not suggestion.get("strategy"):
        raise HTTPException(status_code=409, detail="This proposal has no strategy, so its result could never be judged; decline it.")


@router.post("/{suggestion_id}/approve")
async def approve_suggestion(
    suggestion_id: str,
    user: User = Depends(get_current_user),
    store: SuggestionStore = Depends(get_suggestion_store),
    ledger: LedgerStore = Depends(get_ledger_store),
    mark_price=Depends(get_mark_price),
    option_premium=Depends(get_option_premium),
):
    suggestion = await store.get(user.id, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="No such suggestion")
    if suggestion["status"] != "PENDING":
        raise HTTPException(
            status_code=409, detail=f"Suggestion already {suggestion['status'].lower()}"
        )
    _require_strategy(suggestion)

    # Claim before filling, as approve-live does: two approvals at once (a
    # page tap and a chat confirm) used to both book a fill.
    if await store.decide(user.id, suggestion_id, status="SENDING", reason="paper") is None:
        raise HTTPException(status_code=409, detail="This proposal was already decided or has expired.")
    try:
        price = (
            await option_premium(user.id, suggestion["symbol"])
            if suggestion.get("option_contract")
            else await mark_price(suggestion["symbol"])
        )
        order = await execute_suggestion(suggestion, ledger, price)
    except Exception:
        await store.settle(user.id, suggestion_id, "PENDING", reason=None)
        raise
    return await store.settle(user.id, suggestion_id, "EXECUTED", order_id=order.id, reason=None)


@router.post("/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: str,
    body: RejectRequest = RejectRequest(),
    user: User = Depends(get_current_user),
    store: SuggestionStore = Depends(get_suggestion_store),
):
    decided = await store.decide(user.id, suggestion_id, status="REJECTED", reason=body.reason)
    if decided is None:
        raise HTTPException(status_code=404, detail="No such pending suggestion")
    return decided


async def _options_broker(user_id: str):
    """The user's own account, if it can place option orders. An approval is
    the user's decision, so it never trades the AI account."""
    from backend.brokers.roles import RoleUnavailable, adapter_for

    try:
        adapter = await adapter_for(user_id, "mine", get_credential_store(), db.redis)
    except RoleUnavailable:
        return None
    return adapter if getattr(adapter, "supports_options", False) else None


def get_options_broker():
    """Injected so tests can approve live against a fake broker."""
    return _options_broker


async def _mine_broker(user_id: str):
    """The user's own account for an equity approved with real money. Never
    the AI account (backend/brokers/roles.py)."""
    from backend.brokers.roles import RoleUnavailable, adapter_for

    try:
        return await adapter_for(user_id, "mine", get_credential_store(), db.redis)
    except RoleUnavailable:
        return None


def get_mine_broker():
    """Injected so tests can approve an equity live against a fake broker."""
    return _mine_broker


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/{suggestion_id}/approve-live")
async def approve_suggestion_live(
    suggestion_id: str,
    user: User = Depends(get_current_user),
    store: SuggestionStore = Depends(get_suggestion_store),
    ledger: LedgerStore = Depends(get_ledger_store),
    options_broker=Depends(get_options_broker),
    mine_broker=Depends(get_mine_broker),
    mark_price=Depends(get_mark_price),
):
    """Sends a proposal to the user's own broker account as a real order --
    a person's tap placing real money, so: never the AI account, not on a day
    the kill-switch tripped, and claimed before the order goes out so a
    double tap cannot send two. An option goes as a NRML order on a broker
    that trades options; an equity goes as a MARKET order (CNC for a
    long-term proposal, MIS for intraday) in market hours, within the
    per-trade cap."""
    suggestion = await store.get(user.id, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="No such suggestion")
    if suggestion["status"] != "PENDING":
        raise HTTPException(status_code=409, detail=f"Suggestion already {suggestion['status'].lower()}")
    _require_strategy(suggestion)
    now = _now()
    today = now.astimezone(IST).date()
    if await KillSwitchStore(db.db).is_tripped(user.id, today):
        raise HTTPException(status_code=409, detail="Daily loss limit hit today: no new live orders")
    if not suggestion.get("option_contract"):
        return await _approve_equity_live(suggestion, user.id, store, ledger, mine_broker, mark_price, now)
    # Same rails as an equity approval: market hours, and the per-trade cap on
    # what the order ties up (margin for a sold option, else premium x qty).
    from backend.engine.autorun import in_session

    if not in_session(now):
        raise HTTPException(status_code=409, detail="The market is closed; live orders go only between 9:15 AM and 3:30 PM IST on weekdays.")
    terms = suggestion["option_contract"]
    exposure = terms.get("margin_estimate") or (terms.get("premium_estimate") or 0) * suggestion["quantity"]
    cap = (await PrefsStore(db.db).get(user.id))["per_trade_cap"]
    if exposure > cap:
        raise HTTPException(status_code=409, detail=f"₹{exposure:,.0f} is over your per-trade cap of ₹{cap:,.0f}.")
    contract = await InstrumentMaster(db.db).get("NFO", suggestion["symbol"])
    if contract is None:
        raise HTTPException(status_code=400, detail=f"Unknown option contract {suggestion['symbol']!r}")
    adapter = await options_broker(user.id)
    if adapter is None:
        raise HTTPException(status_code=409, detail="Connect Kite or Upstox in Settings to trade options live.")

    if await store.decide(user.id, suggestion_id, status="SENDING", reason="live") is None:
        raise HTTPException(status_code=409, detail="This proposal was already decided or has expired.")
    try:
        order, broker_status, filled = await execute_option_suggestion_live(
            suggestion, ledger, adapter, contract, LiveOrderStore(db.db),
        )
    except Exception as exc:
        logger.warning("approve-live: order for suggestion %s not placed: %s", suggestion_id, exc)
        await store.settle(user.id, suggestion_id, "PENDING", reason=f"Broker refused: {exc}")
        raise HTTPException(status_code=502, detail=f"Your broker did not take the order: {exc}")

    if filled > 0:
        status, reason = "EXECUTED", None
    elif broker_status in ("REJECTED", "CANCELLED"):
        status, reason = "PENDING", f"Broker {broker_status.lower()} the order"
    else:
        status, reason = "SENT", "Placed with your broker, not filled yet"
    return await store.settle(
        user.id, suggestion_id, status, reason=reason, order_id=order.id, venue="live",
        filled_quantity=filled,
    )


async def _approve_equity_live(suggestion, user_id, store, ledger, mine_broker, mark_price, now) -> dict:
    from backend.engine.autorun import in_session
    from backend.suggestions.service import execute_live_order

    if not in_session(now):
        raise HTTPException(status_code=409, detail="The market is closed; live orders go only between 9:15 AM and 3:30 PM IST on weekdays.")
    if suggestion["side"] == "SELL":
        # An equity SELL proposal exits a paper position; sent live it would
        # sell the user's own shares, which that position never bought.
        raise HTTPException(status_code=409, detail="This proposal exits a paper position; approve it on paper. Sell your own shares from Mine → Holdings.")
    adapter = await mine_broker(user_id)
    if adapter is None:
        raise HTTPException(status_code=409, detail="Connect your broker and set it as My account in Settings to approve with real money.")
    value = await mark_price(suggestion["symbol"]) * suggestion["quantity"]
    cap = (await PrefsStore(db.db).get(user_id))["per_trade_cap"]
    if value > cap:
        raise HTTPException(status_code=409, detail=f"₹{value:,.0f} is over your per-trade cap of ₹{cap:,.0f}.")

    if await store.decide(user_id, suggestion["id"], status="SENDING", reason="live") is None:
        raise HTTPException(status_code=409, detail="This proposal was already decided or has expired.")
    order = Order(
        id=str(uuid.uuid4()), symbol=suggestion["symbol"], side=Side(suggestion["side"]),
        quantity=suggestion["quantity"], order_type="MARKET",
        product="CNC" if suggestion["mode"] == "LONGTERM" else "MIS",
        strategy_name=suggestion.get("strategy"), suggestion_id=suggestion["id"],
    )
    try:
        _, broker_status, filled = await execute_live_order(
            order, ledger, adapter, LiveOrderStore(db.db), "approve", f"Approved proposal {suggestion['id']}",
        )
    except Exception as exc:
        logger.warning("approve-live: equity order for %s not placed: %s", suggestion["id"], exc)
        await store.settle(user_id, suggestion["id"], "PENDING", reason=f"Broker refused: {exc}")
        raise HTTPException(status_code=502, detail=f"Your broker did not take the order: {exc}")

    if filled > 0:
        status, reason = "EXECUTED", None
    elif broker_status in ("REJECTED", "CANCELLED"):
        status, reason = "PENDING", f"Broker {broker_status.lower()} the order"
    else:
        status, reason = "SENT", "Placed with your broker, not filled yet"
    return await store.settle(
        user_id, suggestion["id"], status, reason=reason, order_id=order.id, venue="live",
        filled_quantity=filled,
    )
