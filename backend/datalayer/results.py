"""Results announcement times per symbol, past and upcoming, for the post-results setup
(`forecast/setups.py::results_drift`). Market-wide reference data: no user_id.

`results_dates`: one doc per symbol, {_id: symbol, at: [naive IST datetimes, sorted], checked: ISO date}.
Source: yfinance earnings dates (deep for large caps, patchy for small ones).

    python -m backend.datalayer.results     # fetch every bars symbol now, no per-run cap
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from backend.datalayer.bars import ticker, today_ist

logger = logging.getLogger(__name__)

COLL = "results_dates"
STALE_DAYS = 3     # re-check a symbol this often: Indian boards give ~5 days' notice of a results meeting
FULL, RECENT = 100, 12  # rows asked of yfinance for a new symbol / a re-check (12 ~ the last 3 years + upcoming)
MAX_PER_RUN = 80   # per daily pass, oldest check first: ~1 min, every symbol within 3 days
PAUSE = 0.5        # seconds between symbols: be gentle with Yahoo


def _fetch_sync(tkr: str, limit: int) -> list[datetime]:
    """The only network call."""
    import yfinance as yf

    d = yf.Ticker(tkr).get_earnings_dates(limit=limit)
    return [] if d is None else sorted(d.index.tz_convert("Asia/Kolkata").tz_localize(None).to_pydatetime())


def merge(old: list[datetime], got: list[datetime]) -> list[datetime]:
    """A fetch replaces everything from its earliest row on (dates move); older stored rows stay. Pure."""
    return old if not got else [a for a in old if a < got[0]] + got


async def refresh(db, symbols, now: Optional[datetime] = None, cap: Optional[int] = MAX_PER_RUN) -> int:
    """Fetches up to `cap` symbols not checked in STALE_DAYS (oldest first); returns how many succeeded."""
    today = today_ist(now)
    docs = {d["_id"]: d async for d in db[COLL].find({"_id": {"$in": list(symbols)}})}
    stale = sorted((s for s in symbols if s not in docs
                    or date.fromisoformat(docs[s]["checked"]) <= today - timedelta(days=STALE_DAYS)),
                   key=lambda s: docs[s]["checked"] if s in docs else "")
    done = 0
    for s in stale[:cap]:
        old = _naive(docs.get(s, {}).get("at", []))
        try:
            got = await asyncio.to_thread(_fetch_sync, ticker(s), RECENT if s in docs else FULL)
        except Exception as exc:
            logger.warning("results dates: %s failed: %s", s, exc)
            continue
        await db[COLL].replace_one({"_id": s}, {"at": merge(old, got), "checked": today.isoformat()}, upsert=True)
        done += 1
        await asyncio.sleep(PAUSE)
    return done


def _naive(at: list[datetime]) -> list[datetime]:
    """The client is tz_aware (UTC): a stored naive IST time comes back labelled UTC with the same wall clock."""
    return [a.replace(tzinfo=None) for a in at]


async def load(db) -> dict[str, list[datetime]]:
    return {d["_id"]: _naive(d["at"]) async for d in db[COLL].find({}, {"at": 1})}


if __name__ == "__main__":
    from backend.database import db as _db
    from backend.datalayer import bars

    async def _main() -> None:
        await _db.connect_to_database()
        symbols = set(await _db.db[bars.BARS].distinct("symbol")) - {bars.NIFTY}
        print(f"results dates: {await refresh(_db.db, symbols, datetime.now(timezone.utc), cap=None)} of {len(symbols)}")

    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
