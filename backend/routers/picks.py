"""Picks (backend/forecast/): admin-only until the owner's SEBI Research
Analyst registration exists."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth.dependency import require_admin
from backend.auth.models import User
from backend.database import db
from backend.datalayer.bars import today_ist
from backend.forecast.picks import CAVEATS, PICKS, STUDY, forward, rank_key, serve, setup_grades
from backend.marks import mark_prices

router = APIRouter(prefix="/picks", tags=["Picks"], dependencies=[Depends(require_admin)])
DISMISSED = "picks_dismissed"  # {user_id, pick_id, at}: a pick the user skipped leaves their `shown` list


async def served_today(user_id: str | None = None) -> tuple:
    """(latest, picks, study, served): the latest pass's candidates and the filtered list the UI shows,
    minus the picks `user_id` skipped."""
    latest = await db.db[PICKS].find_one({}, {"date": 1}, sort=[("date", -1)])
    picks = await db.db[PICKS].find({"date": latest["date"]}).to_list(length=None) if latest else []
    picks.sort(key=rank_key, reverse=True)
    today = today_ist()
    # Every earlier pick still before its due date (a 60-day setup stays up to ~3 months).
    older = await db.db[PICKS].find({"date": {"$lt": latest["date"]}, "due_date": {"$gt": today.isoformat()}}).to_list(length=None) if latest else []
    study = await db.db[STUDY].find_one({"_id": "latest"}) or {}
    prices = await mark_prices(db.db, {p["symbol"] for p in older + picks})
    served = serve(picks, older, prices, today, setup_grades(study))
    if user_id:
        skipped = set(await db.db[DISMISSED].distinct("pick_id", {"user_id": user_id}))
        served["shown"] = [p for p in served["shown"] if p["_id"] not in skipped]
    return latest, picks, study, served


@router.get("")
async def picks_today(user: User = Depends(require_admin)):
    latest, picks, study, served = await served_today(user.id)
    scored = await db.db[PICKS].find({"outcome": {"$ne": None}}, {"p_up": 1, "outcome": 1, "backfilled": 1}).to_list(length=None)
    return {
        "date": latest and latest["date"],
        "picks": picks,  # every candidate of the latest pass (backward compatible); the UI reads `shown`
        **served,
        "setups": study.get("setups", []),
        "grades": setup_grades(study),
        "as_of": study.get("as_of"),
        "forward": forward(scored),
        "caveats": CAVEATS,
    }


@router.get("/history")
async def picks_history(days: int = Query(90, ge=1, le=3650)):
    since = (today_ist() - timedelta(days=days)).isoformat()
    picks = await db.db[PICKS].find({"date": {"$gte": since}}).sort([("date", -1), ("symbol", 1)]).to_list(length=None)
    return {"picks": picks}


@router.post("/{pick_id}/dismiss")
async def dismiss_pick(pick_id: str, user: User = Depends(require_admin)):
    """Skip a pick: it stops showing on this user's Ideas list (the pick itself and its record are untouched)."""
    if not await db.db[PICKS].find_one({"_id": pick_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="No such pick")
    await db.db[DISMISSED].update_one({"user_id": user.id, "pick_id": pick_id},
                                      {"$set": {"at": datetime.now(timezone.utc)}}, upsert=True)
    return {"dismissed": pick_id}
