"""/suggestions/* -- the approve/reject inbox for AI trade proposals.

Long-term signals never execute themselves (see backend/suggestions/sink.py);
they land here carrying the sizing, stop, target, reason codes and score the
engine computed, and wait for a decision. Approving is the only place in the
app where a person causes a trade.
"""

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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
from backend.suggestions.scan import scan_universe
from backend.suggestions.service import execute_suggestion
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
    universe: Optional[list[str]] = None  # defaults to the user's saved universe


@router.post("/scan", status_code=202)
async def scan_now(
    body: ScanRequest = ScanRequest(),
    user: User = Depends(get_current_user),
):
    """Runs in the background: a scan pulls a year of daily history per
    symbol, which is minutes for a full universe -- far too long to hold an
    HTTP request open. New suggestions appear in the inbox as they land."""
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
    limit: int = 100,
    user: User = Depends(get_current_user),
    store: SuggestionStore = Depends(get_suggestion_store),
):
    return await store.list(user.id, mode=mode, status=status, limit=limit)


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

    price = (
        await option_premium(user.id, suggestion["symbol"])
        if suggestion.get("option_contract")
        else await mark_price(suggestion["symbol"])
    )
    order = await execute_suggestion(suggestion, ledger, price)

    decided = await store.decide(user.id, suggestion_id, status="EXECUTED", order_id=order.id)
    if decided is None:
        # Someone decided it between the read above and here; the order is
        # already in the ledger, so say so loudly rather than silently.
        logger.warning("suggestion %s was decided concurrently after order %s", suggestion_id, order.id)
        raise HTTPException(status_code=409, detail="Suggestion was decided concurrently")
    return decided


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
