"""Stored AI summaries, read only (backend/summaries/). Nothing here calls a
model: the generators run on their own schedules. Every read is scoped to the
signed-in user; `summary` is null until the first one is written."""

from datetime import datetime, timezone

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
