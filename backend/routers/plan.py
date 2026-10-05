"""Today's AI game plan for the signed-in user: the plan in force, its
versions (pre-open and revisions), and how plans have scored against no
plan in the nightly replay (backend/plan/)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.engine.session import IST
from backend.plan import store
from backend.plan.replay import SCORECARDS, weeks_beating

router = APIRouter(prefix="/plan", tags=["Plan"])
VERSION_FIELDS = ("version", "at", "trigger", "risk_multiplier", "skip_day", "rationale")


@router.get("/today")
async def plan_today(user: User = Depends(get_current_user)):
    day = datetime.now(timezone.utc).astimezone(IST).date()
    versions = await store.versions(db.db, user.id, day)
    cards = await db.db[SCORECARDS].find({"user_id": user.id}, {"_id": 0, "user_id": 0}) \
        .sort("date", -1).to_list(length=10)
    return {
        "plan": await store.current(db.redis, user.id, day),
        "versions": [{k: v.get(k) for k in VERSION_FIELDS} for v in versions],
        "scorecards": cards,
        "weeks_beating": await weeks_beating(db.db, user.id),
    }
