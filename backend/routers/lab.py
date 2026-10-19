"""Research Lab run records (backend/lab/runs.py), admin only."""

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth.dependency import require_admin
from backend.database import db
from backend.lab.runs import LabRunStore

router = APIRouter(prefix="/lab", tags=["Lab"], dependencies=[Depends(require_admin)])


@router.get("/runs")
async def list_runs(kind: str | None = None, name: str | None = None, limit: int = Query(50, ge=1, le=200)):
    runs = await LabRunStore(db.db).list(kind=kind, name=name, limit=limit)
    return {"runs": [{k: v for k, v in r.items() if k != "folds"} for r in runs]}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = await LabRunStore(db.db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
