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

from backend.auth.dependency import get_current_user, require_admin
from backend.auth.models import User
from backend.database import db
from backend.data.providers.yfinance_provider import YFinanceProvider
from backend.engine.persistence import LedgerStore, mine_book
from backend.ws.publish import publisher_for
from backend.auth.broker_credentials import get_credential_store
from backend.instruments.master import InstrumentMaster
from backend.prefs import PrefsStore
from backend.rate_limit import allow
from backend.suggestions.scan import scan_universe
from backend.brokers.protocol import BrokerSessionState
from backend.core.models import Order, Side
from backend.brokers.registry import BROKERS, get_broker_adapter
from backend.engine.execution.live_order_store import LiveOrderStore
from backend.engine.session import IST
from backend.risk import live_confirm
from backend.risk.kill_switch import KillSwitchStore
from backend.suggestions.service import execute_option_suggestion_live
from backend.suggestions.store import SuggestionStore
from backend.suggestions.thesis import attach_theses

logger = logging.getLogger(__name__)

# Admin-only, like Picks (owner decision 2026-10-24, audit W1): engine ideas read as advice.
router = APIRouter(prefix="/suggestions", tags=["Suggestions"], dependencies=[Depends(require_admin)])


def get_suggestion_store() -> SuggestionStore:
    return SuggestionStore(db.db)


def get_ledger_store(user: User = Depends(get_current_user)) -> LedgerStore:
    """Approvals are real orders on the user's own account: their book."""
    return LedgerStore(db.db, user_id=mine_book(user.id), on_change=publisher_for(user.id))


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
    from backend.risk.paper_gate import for_mine

    # Pending ideas only from strategies proven on the AI account.
    return await for_mine(db.db, user.id, await store.list(user.id, mode=mode, status=status, limit=limit))


def _require_strategy(suggestion: dict) -> None:
    """A fill no strategy owns can never be judged: approving one is refused."""
    if not suggestion.get("strategy"):
        raise HTTPException(status_code=409, detail="This proposal has no strategy, so its result could never be judged; decline it.")


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


class ApproveLiveRequest(BaseModel):
    confirm_token: Optional[str] = None  # from the first call


def _order_terms(suggestion: dict) -> dict:
    """What the second tap is bound to: a change to any of these between the
    taps voids the token."""
    return {k: suggestion.get(k) for k in ("symbol", "side", "quantity", "mode", "option_contract")}


@router.post("/{suggestion_id}/approve-live")
async def approve_suggestion_live(
    suggestion_id: str,
    body: ApproveLiveRequest = ApproveLiveRequest(),
    user: User = Depends(get_current_user),
    store: SuggestionStore = Depends(get_suggestion_store),
    ledger: LedgerStore = Depends(get_ledger_store),
    options_broker=Depends(get_options_broker),
    mine_broker=Depends(get_mine_broker),
    mark_price=Depends(get_mark_price),
):
    """Two calls, both server-checked: without `confirm_token` it returns
    NEEDS_SECOND_TAP and a token (backend/risk/live_confirm.py); with it,
    the token is spent and the order is placed with every check run again."""
    suggestion = await store.get(user.id, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="No such suggestion")
    if suggestion["status"] != "PENDING":
        raise HTTPException(status_code=409, detail=f"Suggestion already {suggestion['status'].lower()}")
    subject, terms = f"suggestion:{suggestion_id}", _order_terms(suggestion)
    if not body.confirm_token:
        token = await live_confirm.issue(db.redis, user.id, subject, terms)
        return {"status": "NEEDS_SECOND_TAP", "result": live_confirm.NEEDS_SECOND_TAP,
                "confirm_token": token, "expires_in": live_confirm.TTL_SECONDS}
    try:
        await live_confirm.redeem(db.redis, user.id, subject, terms, body.confirm_token)
    except live_confirm.TokenRefused as exc:
        return exc.response()
    return await place_live_approval(suggestion_id, user, store, ledger, options_broker, mine_broker, mark_price)


async def place_live_approval(suggestion_id: str, user, store, ledger, options_broker, mine_broker, mark_price):
    """Sends a proposal to the user's own broker account as a real order --
    a person's tap placing real money, so: never the AI account, not on a day
    the kill-switch tripped, and claimed before the order goes out so a
    double tap cannot send two. An option goes as a NRML order on a broker
    that trades options; an equity goes as a MARKET order (CNC for a
    long-term proposal, MIS for intraday) in market hours. The per-trade
    cap is the AI account's rail (autopilot/fence.py), so it does not apply
    here: the user's own account trades what the user approves."""
    suggestion = await store.get(user.id, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="No such suggestion")
    if suggestion["status"] != "PENDING":
        raise HTTPException(status_code=409, detail=f"Suggestion already {suggestion['status'].lower()}")
    _require_strategy(suggestion)
    from backend.risk.paper_gate import for_mine
    if not await for_mine(store.collection.database, user.id, [suggestion]):
        raise HTTPException(status_code=409, detail=(
            f"{suggestion.get('strategy')} has not earned real money yet: it needs a passing backtest and "
            "a passing paper record on the AI account."))
    now = _now()
    today = now.astimezone(IST).date()
    if await KillSwitchStore(db.db).is_tripped(user.id, today):
        raise HTTPException(status_code=409, detail="Daily loss limit hit today: no new live orders")
    if not suggestion.get("option_contract"):
        return await _approve_equity_live(suggestion, user.id, store, ledger, mine_broker, mark_price, now)
    # Same rails as an equity approval: market hours.
    from backend.engine.autorun import in_session

    if not in_session(now):
        raise HTTPException(status_code=409, detail="The market is closed; live orders go only between 9:15 AM and 3:30 PM IST on weekdays.")
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
        raise HTTPException(status_code=409, detail="This proposal exits a paper position; approve it on paper. Sell your own shares from Portfolio → Holdings.")
    adapter = await mine_broker(user_id)
    if adapter is None:
        raise HTTPException(status_code=409, detail="Connect your broker and set it as My account in Settings to approve with real money.")
    prefs = await PrefsStore(db.db).get(user_id)
    from backend.mine.events import buy_blocked

    why = await buy_blocked(db.db, prefs, suggestion["symbol"], now.astimezone(IST).date())
    if why:
        raise HTTPException(status_code=409, detail=why)

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
