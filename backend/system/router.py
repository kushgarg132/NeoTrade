"""Admin-only system views: live status for the handbook, and the backlog."""

from fastapi import APIRouter, Depends

from backend.auth.dependency import require_admin
from backend.auth.models import User
from backend.database import db
from backend.system import status

router = APIRouter()


@router.get("/system/status")
async def system_status(_admin: User = Depends(require_admin)):
    return await status.cached_status(db.db, db.redis)
