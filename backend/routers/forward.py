"""Forward record scorecard and records (backend/forward), admin only."""

from fastapi import APIRouter, Depends, Query

from backend.auth.dependency import require_admin
from backend.database import db
from backend.forward.scorecard import scorecard
from backend.forward.store import ForwardStore

router = APIRouter(prefix="/forward", tags=["Forward"], dependencies=[Depends(require_admin)])


@router.get("/scorecard")
async def get_scorecard():
    return {"rows": await scorecard(db.db)}


@router.get("/records")
async def list_records(source: str | None = None, name: str | None = None, limit: int = Query(200, ge=1, le=500)):
    records = await ForwardStore(db.db).list(source=source, name=name, limit=limit)
    return {"records": [{**{k: v for k, v in r.items() if k != "_id"}, "id": r["_id"]} for r in records]}
