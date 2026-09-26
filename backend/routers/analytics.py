"""/analytics/* -- the numbers behind the dashboard's P&L cards."""

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends

from backend.analytics import compute_pnl, compute_scorecard
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.core.models import Venue
from backend.database import db
from backend.engine.persistence import LedgerStore
from backend.ws.publish import publisher_for
from backend.marks import mark_prices
from backend.prefs import PrefsStore

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def get_ledger_store(user: User = Depends(get_current_user)) -> LedgerStore:
    return LedgerStore(db.db, user_id=user.id, on_change=publisher_for(user.id))


@router.get("/pnl")
async def get_pnl(venue: Optional[Venue] = None, ledger: LedgerStore = Depends(get_ledger_store)):
    """`venue=paper` is the Paper tab's book, `venue=live` real engine orders;
    omitted, both combined."""
    positions = await ledger.get_open_positions(venue=venue)
    marks = await mark_prices(db.db, positions.keys())
    return await compute_pnl(ledger, marks, venue=venue)


logger = logging.getLogger(__name__)
_NIFTY_CACHE: dict = {"at": 0.0, "points": None}
NIFTY_CACHE_SECONDS = 60 * 60


async def _nifty_points():
    """A year of NIFTY 50 closes, cached an hour: the benchmark only needs
    daily closes, and every scorecard view would otherwise refetch them."""
    from backend.routers.market_data import _fetch_index_detail_sync

    if _NIFTY_CACHE["points"] is None or time.time() - _NIFTY_CACHE["at"] > NIFTY_CACHE_SECONDS:
        detail = await asyncio.to_thread(_fetch_index_detail_sync, "^NSEI", "NIFTY 50")
        _NIFTY_CACHE.update(at=time.time(), points=(detail or {}).get("points"))
    return _NIFTY_CACHE["points"]


def nifty_return(points, first_day: str):
    """NIFTY's % move from the close before `first_day` to the latest close:
    what simply holding the index would have made over the same stretch."""
    before = [p for p in points if p["date"] < first_day]
    if not before or not points:
        return None
    start = before[-1]["close"]
    return (points[-1]["close"] - start) / start * 100


@router.get("/scorecard")
async def get_scorecard(
    venue: Optional[Venue] = "paper",
    user: User = Depends(get_current_user),
    ledger: LedgerStore = Depends(get_ledger_store),
):
    """The engine's track record, day by day and per strategy, net of
    charges -- what decides whether a strategy has earned real money."""
    prefs = await PrefsStore(db.db).get(user.id)
    card = await compute_scorecard(ledger, venue, prefs["account_size"])
    card["nifty_return_pct"] = None
    first_day = card["totals"]["first_day"]
    if first_day:
        try:
            points = await _nifty_points()
            card["nifty_return_pct"] = nifty_return(points or [], first_day)
        except Exception as e:
            logger.warning("scorecard: NIFTY benchmark unavailable: %s", e)
    return card
