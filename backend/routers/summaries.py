"""Stored AI summaries, read only (backend/summaries/). Nothing here calls a
model: the generators run on their own schedules. Every read is scoped to the
signed-in user; `summary` is null until the first one is written."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.engine.session import IST
from backend.summaries import core

router = APIRouter(prefix="/summaries", tags=["Summaries"])


def _today() -> str:
    return datetime.now(timezone.utc).astimezone(IST).date().isoformat()


@router.get("/day")
async def day(user: User = Depends(get_current_user)):
    """Today's "Your day": the post-close one once it exists, else the pre-market one."""
    for phase in ("post", "pre"):
        doc = core.shown(await core.get(db.db, user.id, "day", f"{_today()}:{phase}"))
        if doc:
            return {"summary": {**doc, "phase": phase}}
    return {"summary": None}


@router.get("/holdings")
async def holdings(user: User = Depends(get_current_user)):
    """{notes: {action id: {text, at}}} for the last two weeks of Your holdings rows."""
    since = datetime.now(timezone.utc) - timedelta(days=15)
    notes = {}
    async for d in db.db[core.COLLECTION].find({"user_id": user.id, "kind": "holding", "at": {"$gte": since}}).limit(200):
        notes[d["key"]] = {k: v for k, v in core.shown(d).items() if k != "key"}
    return {"notes": notes}


@router.get("/activity")
async def activity(user: User = Depends(get_current_user)):
    """The latest "what the AI did today and why" (written once a day after the close)."""
    return {"summary": core.shown(await core.latest(db.db, user.id, "activity"))}
