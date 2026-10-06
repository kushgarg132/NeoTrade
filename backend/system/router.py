"""Admin-only system views: live status for the handbook, and the backlog."""

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.dependency import require_admin
from backend.auth.models import User
from backend.database import db
from backend.system import backlog, status

router = APIRouter()


@router.get("/system/status")
async def system_status(_admin: User = Depends(require_admin)):
    return await status.cached_status(db.db, db.redis)


@router.get("/system/backlog")
async def list_backlog(_admin: User = Depends(require_admin)):
    return {"items": await backlog.list_items(db.db)}


@router.post("/system/backlog")
async def create_backlog_item(item: backlog.ItemIn, _admin: User = Depends(require_admin)):
    return await backlog.create(db.db, item)


@router.patch("/system/backlog/{item_id}")
async def update_backlog_item(item_id: str, patch: backlog.ItemPatch, _admin: User = Depends(require_admin)):
    item = await backlog.update(db.db, item_id, patch)
    if item is None:
        raise HTTPException(status_code=404, detail="No such backlog item")
    return item


@router.delete("/system/backlog/{item_id}")
async def delete_backlog_item(item_id: str, _admin: User = Depends(require_admin)):
    if not await backlog.delete(db.db, item_id):
        raise HTTPException(status_code=404, detail="No such backlog item")
    return {"ok": True}
