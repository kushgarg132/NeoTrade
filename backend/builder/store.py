"""The `built_strategies` collection: every strategy the builder drafted, with
its verdict. Only `active` docs run; `refresh` copies them into the in-memory
cache that strategies/registry.py builds from (strategies/ itself does no I/O).

Doc: slug, spec, thesis, description, drafted_at, status
("testing"|"rejected"|"active"|"retired"), verdict, metrics
({"year": {...}, "holdout": {...}}), trials, sharpe, params.
"""
import logging
from datetime import timedelta
from typing import Callable, Optional

from backend.datalayer import bars
from backend.strategies import built
from backend.strategies.blocks.regime import regime_by_day

COLLECTION = "built_strategies"
logger = logging.getLogger(__name__)


async def refresh(db) -> list[dict]:
    """Loads the active specs into the strategy cache; call once per entry point."""
    try:
        rows = await db[COLLECTION].find({"status": "active"}, {"_id": 0}).to_list(None)
    except Exception as exc:  # a store failure must not stop a run; keep the cache as it was
        logger.warning("could not load built strategies: %s", exc)
        return []
    docs = [d for d in rows if isinstance(d, dict) and d.get("slug") and isinstance(d.get("spec"), dict)]
    if len(docs) < len(rows):
        logger.warning("skipping %d malformed built strategy doc(s)", len(rows) - len(docs))
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
    try:
        return regime_by_day(await bars.nifty_closes(db, bars.today_ist() - timedelta(days=400)))
    except Exception as exc:
        logger.warning("could not load the Nifty regime: %s", exc)
        return lambda d: None
