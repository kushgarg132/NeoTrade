"""The user's weekly report (backend/reports/weekly.py)."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth.dependency import get_current_user
from backend.database import db
from backend.engine.session import IST
from backend.auth.models import User
from backend.reports import weekly

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/weekly")
async def weekly_report(week: Optional[str] = Query(None), user: User = Depends(get_current_user)):
    try:
        week = week or weekly.last_completed(datetime.now(timezone.utc).astimezone(IST).date())
        return await weekly.build(db.db, user.id, week)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
