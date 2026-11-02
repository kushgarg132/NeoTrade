"""The AI account's daily plan for the signed-in user: the latest one the
morning pass stored (backend/autopilot/rotation.py::plan)."""

from fastapi import APIRouter, Depends

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.autopilot.rotation import PLANS
from backend.database import db

router = APIRouter(prefix="/plan", tags=["Plan"])


@router.get("/today")
async def plan_today(user: User = Depends(get_current_user)):
    plan = await db.db[PLANS].find_one({"user_id": user.id}, {"_id": 0, "user_id": 0}, sort=[("date", -1)])
    return {"plan": plan}
