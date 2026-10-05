"""GET /scanner -- the user's universe swept for breakouts and pullbacks.
Rules live in backend.research.scanner; this only wires prefs and the data:
the shared daily_bars store first, one batched download for whatever it lacks."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.datalayer import bars
from backend.engine.session import IST
from backend.prefs import PrefsStore
from backend.research.scanner import ScanResult, fetch_daily, find_setups

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Scanner"])


class ScanResponse(ScanResult):
    scan_time: datetime


async def _stored(universe: list[str]) -> dict:
    return await bars.read(db.db, universe, bars.today_ist() - timedelta(days=365))


async def get_universe(user: User = Depends(get_current_user)) -> list[str]:
    return (await PrefsStore(db.db).get(user.id))["universe"]


@router.get("/scanner", response_model=ScanResponse)
async def scan(universe: list[str] = Depends(get_universe)) -> ScanResponse:
    now = datetime.now(IST)
    frames = await _stored(universe) if universe else {}
    missing = [s for s in universe if s not in frames]
    if missing:
        try:
            frames |= await fetch_daily(missing)
        except Exception:
            logger.exception("scanner download failed for %d symbols", len(missing))
            if not frames:  # nothing from the store either; otherwise the rest show as "no data"
                raise HTTPException(502, "The market data provider did not respond. Try again in a minute.")
    result = find_setups(frames, universe, now)
    return ScanResponse(**result.model_dump(), scan_time=now)
