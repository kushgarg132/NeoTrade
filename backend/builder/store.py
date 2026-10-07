"""The `built_strategies` collection: every strategy the builder drafted, with
its verdict. Only `active` docs run; `refresh` copies them into the in-memory
cache that strategies/registry.py builds from (strategies/ itself does no I/O).

Doc: slug, owner_id (None/absent = the AI's, global), spec, thesis, description, drafted_at, status
("testing"|"rejected"|"active"|"retired"), verdict, metrics
({"year": {...}, "holdout": {...}}), trials, sharpe, params.
"""
import logging
import math
from datetime import timedelta
from typing import Callable, Optional

from backend.datalayer import bars
from backend.strategies import built
from backend.strategies.blocks.regime import regime_by_day

COLLECTION = "built_strategies"
REGIME_DAYS = 800  # a 365-day backtest plus 200 trading days of warmup, with margin
logger = logging.getLogger(__name__)


RUNS = "builder_runs"  # one doc per ISO week the job was started (backend/builder/draft.py::start_if_due)


async def ensure_indexes(db) -> None:
    """Unique slugs, and one run claim per week: the claim's upsert is only atomic with this index."""
    try:
        await db[COLLECTION].create_index("slug", unique=True)
        await db[RUNS].create_index("week", unique=True)
    except Exception as exc:  # startup must not fail on it; the run lock still keeps one job at a time
        logger.error("built strategy indexes not created: %s", exc)


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


async def visible(db, user_id: str) -> list[dict]:
    """The AI's drafts plus this user's own, newest first."""
    return await db[COLLECTION].find({"owner_id": {"$in": [None, user_id]}}, {"_id": 0}).sort("drafted_at", -1).to_list(None)


async def trial_sharpes(db, owner_id: Optional[str] = None) -> list[float]:
    """Sharpe of every draft this owner (None = the AI) already tested, for the deflated-Sharpe trial count."""
    rows = await db[COLLECTION].find({"status": {"$ne": "testing"}, "owner_id": owner_id}, {"sharpe": 1}).to_list(None)
    return [s for r in rows if isinstance(s := r.get("sharpe"), (int, float)) and math.isfinite(s)]


async def regime_of(db) -> Callable[[object], Optional[str]]:
    """The Nifty regime lookup built strategies filter on. The 200-day average needs ~290 calendar
    days of closes before the first day it answers, so a year-long backtest needs ~800 days loaded."""
    try:
        return regime_by_day(await bars.nifty_closes(db, bars.today_ist() - timedelta(days=REGIME_DAYS)))
    except Exception as exc:
        logger.warning("could not load the Nifty regime: %s", exc)
        return lambda d: None
