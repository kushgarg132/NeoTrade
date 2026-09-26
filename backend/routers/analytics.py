"""/analytics/* -- the numbers behind the dashboard's P&L cards."""

from typing import Optional

from fastapi import APIRouter, Depends

from backend.analytics import compute_pnl
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.core.models import Venue
from backend.database import db
from backend.engine.persistence import LedgerStore
from backend.ws.publish import publisher_for
from backend.marks import mark_prices

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
