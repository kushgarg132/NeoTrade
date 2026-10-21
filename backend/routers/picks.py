"""Picks (backend/forecast/): admin-only until the owner's SEBI Research
Analyst registration exists."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query

from backend.auth.dependency import require_admin
from backend.database import db
from backend.datalayer.bars import today_ist
from backend.forecast.picks import CAVEATS, PICKS, STUDY, forward, has_edge, rank_key, serve, setup_edges
from backend.marks import mark_prices

router = APIRouter(prefix="/picks", tags=["Picks"], dependencies=[Depends(require_admin)])


async def served_today() -> tuple:
    """(latest, picks, study, served): the latest pass's candidates and the filtered list the UI shows."""
    latest = await db.db[PICKS].find_one({}, {"date": 1}, sort=[("date", -1)])
    picks = await db.db[PICKS].find({"date": latest["date"]}).to_list(length=None) if latest else []
    picks.sort(key=rank_key, reverse=True)
    today = today_ist()
    older = await db.db[PICKS].find({"date": {"$gte": (today - timedelta(days=14)).isoformat(), "$lt": latest["date"]}}).to_list(length=None) if latest else []
    study = await db.db[STUDY].find_one({"_id": "latest"}) or {}
    edges = setup_edges(study)
    prices = await mark_prices(db.db, {p["symbol"] for p in older if has_edge(p, edges)})
    return latest, picks, study, serve(picks, older, prices, today, edges)


@router.get("")
async def picks_today():
    latest, picks, study, served = await served_today()
    scored = await db.db[PICKS].find({"outcome": {"$ne": None}}, {"p_up": 1, "outcome": 1}).to_list(length=None)
    return {
        "date": latest and latest["date"],
        "picks": picks,  # every candidate of the latest pass (backward compatible); the UI reads `shown`
        **served,
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
