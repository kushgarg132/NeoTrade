"""Picks (backend/forecast/): admin-only until the owner's SEBI Research
Analyst registration exists."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query

from backend.auth.dependency import require_admin
from backend.database import db
from backend.datalayer.bars import today_ist
from backend.forecast.picks import CAVEATS, PICKS, STUDY, forward, rank_key

router = APIRouter(prefix="/picks", tags=["Picks"], dependencies=[Depends(require_admin)])


@router.get("")
async def picks_today():
    latest = await db.db[PICKS].find_one({}, {"date": 1}, sort=[("date", -1)])
    picks = await db.db[PICKS].find({"date": latest["date"]}).to_list(length=None) if latest else []
    picks.sort(key=rank_key, reverse=True)
    scored = await db.db[PICKS].find({"outcome": {"$ne": None}}, {"p_up": 1, "outcome": 1}).to_list(length=None)
    study = await db.db[STUDY].find_one({"_id": "latest"}) or {}
    return {
        "date": latest and latest["date"],
        "picks": picks,
        "setups": study.get("setups", []),
        "as_of": study.get("as_of"),
        "forward": forward(scored),
        "caveats": CAVEATS,
    }


@router.get("/history")
async def picks_history(days: int = Query(90, ge=1, le=3650)):
    since = (today_ist() - timedelta(days=days)).isoformat()
    picks = await db.db[PICKS].find({"date": {"$gte": since}}).sort([("date", -1), ("symbol", 1)]).to_list(length=None)
    return {"picks": picks}
