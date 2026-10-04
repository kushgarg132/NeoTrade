"""GET /scanner -- the user's universe swept for breakouts and pullbacks.
Rules live in backend.research.scanner; this only wires prefs and the download."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.engine.session import IST
from backend.prefs import PrefsStore
from backend.research.scanner import ScanResult, fetch_daily, find_setups

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Scanner"])


class ScanResponse(ScanResult):
    scan_time: datetime


async def get_universe(user: User = Depends(get_current_user)) -> list[str]:
    return (await PrefsStore(db.db).get(user.id))["universe"]


@router.get("/scanner", response_model=ScanResponse)
async def scan(universe: list[str] = Depends(get_universe)) -> ScanResponse:
    now = datetime.now(IST)
    frames = {}
    if universe:
        try:
            frames = await fetch_daily(universe)
        except Exception:
            logger.exception("scanner download failed for %d symbols", len(universe))
            raise HTTPException(502, "The market data provider did not respond. Try again in a minute.")
    result = find_setups(frames, universe, now)
    return ScanResponse(**result.model_dump(), scan_time=now)
