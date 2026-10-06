"""The nightly data-quality check (Phase 17.4.3), run at the end of the 16:00
daily pass and shown on the handbook's Jobs panel as `data_quality`.

- stale bars: a covered symbol whose newest `daily_bars` row is behind the
  newest date any symbol has -- its quote keeps failing (delisted, renamed,
  e.g. GMRINFRA in Sept 2026);
- unlisted: a symbol in someone's universe with no NSE instrument;
- silent feeds: a news feed with no new item for SILENT_AFTER (a feed that
  only repeats stories another feed brought first also looks silent).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.datalayer.bars import BARS
from backend.datalayer.news import COLLECTION as NEWS
from backend.datalayer.news_sources import FEEDS

SILENT_AFTER = timedelta(days=3)  # RBI, SEBI and PIB can go a weekend without a release
EXAMPLES = 8


def _names(symbols) -> str:
    symbols = sorted(symbols)
    more = f" +{len(symbols) - EXAMPLES}" if len(symbols) > EXAMPLES else ""
    return ", ".join(symbols[:EXAMPLES]) + more


async def check(db, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    latest = {row["_id"]: row["date"] async for row in db[BARS].aggregate(
        [{"$group": {"_id": "$symbol", "date": {"$max": "$date"}}}])}
    newest = max(latest.values(), default=None)
    stale = [s for s, d in latest.items() if d < newest]

    universe = set()
    async for prefs in db["user_prefs"].find({}, {"universe": 1}):
        universe |= {s.upper().removesuffix(".NS") for s in prefs.get("universe") or []}
    listed = set(await db["instruments"].distinct(
        "tradingsymbol", {"exchange": "NSE", "tradingsymbol": {"$in": sorted(universe)}}))
    unlisted = universe - listed

    heard = set(await db[NEWS].distinct("feeds", {"fetched_at": {"$gte": now - SILENT_AFTER}}))
    silent = [name for name, *_ in FEEDS if name not in heard]

    return {
        "bars_as_of": newest or "none",
        "stale_bars": len(stale), **({"stale": _names(stale)} if stale else {}),
        "unlisted_in_universes": len(unlisted), **({"unlisted": _names(unlisted)} if unlisted else {}),
        "silent_feeds": len(silent), **({"silent": _names(silent)} if silent else {}),
    }
