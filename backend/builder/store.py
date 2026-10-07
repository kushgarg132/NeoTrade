"""The `built_strategies` collection: every strategy the builder drafted, with
its verdict. Only `active` docs run; `refresh` copies them into the in-memory
cache that strategies/registry.py builds from (strategies/ itself does no I/O).

Doc: slug, spec, thesis, description, drafted_at, status
("testing"|"rejected"|"active"|"retired"), verdict, metrics
({"year": {...}, "holdout": {...}}), trials, sharpe, params.
"""
from datetime import timedelta
from typing import Callable, Optional

from backend.datalayer import bars
from backend.strategies import built
from backend.strategies.blocks.regime import regime_by_day

COLLECTION = "built_strategies"


async def refresh(db) -> list[dict]:
    """Loads the active specs into the strategy cache; call once per entry point."""
    docs = await db[COLLECTION].find({"status": "active"}, {"_id": 0}).to_list(None)
    built.set_active(docs)
    return docs


async def all_drafts(db) -> list[dict]:
    return await db[COLLECTION].find({}, {"_id": 0}).sort("drafted_at", -1).to_list(None)


async def insert(db, doc: dict) -> None:
    await db[COLLECTION].insert_one(dict(doc))


async def set_status(db, slug: str, status: str, verdict: str = "", **fields) -> None:
    await db[COLLECTION].update_one({"slug": slug}, {"$set": {"status": status, "verdict": verdict, **fields}})


async def trial_sharpes(db) -> list[float]:
    """Sharpe of every draft already tested, for the deflated-Sharpe trial count."""
    rows = await db[COLLECTION].find({"status": {"$ne": "testing"}}, {"sharpe": 1}).to_list(None)
    return [r["sharpe"] for r in rows if r.get("sharpe") is not None]


async def regime_of(db) -> Callable[[object], Optional[str]]:
    """The Nifty regime lookup built strategies filter on (200-day average needs history)."""
    return regime_by_day(await bars.nifty_closes(db, bars.today_ist() - timedelta(days=400)))
