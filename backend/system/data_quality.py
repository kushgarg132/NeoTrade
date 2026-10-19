"""Data-quality checks (Phase 17.4.3, extended in Phase 21 for truth).

`check` runs at the end of the 16:00 daily pass and is shown on the
handbook's Jobs panel as `data_quality`; it is marked failed when any
`failures` entry exists:

- stale bars: a covered symbol whose newest `daily_bars` row is behind the
  last session whose bars should be in (BARS_READY on the last weekday) --
  a delisted name (GMRINFRA, Sept 2026) or every stock a day late
  (2026-10-15, Upstox history ended at yesterday);
- plus every `live` check below.

Informational, not failures: unlisted universe symbols, and silent news feeds
(a feed that only repeats stories another feed brought first also looks silent).

`live` is cheap and runs on demand (/system status, the admin's Today):

- ingest heartbeats older than twice their loop's interval, or gone (the
  44-hour dead ingest of 2026-10-15);
- the quotes loop failing: no cached quote for any of the first few Nifty
  200 names;
- `scheduler:last_pass` behind the last weekday whose pass should be done;
- the Picks job's study not written for that day.

No NSE holiday calendar exists: weekends are the only gap the checks know,
and `alerts` (the Today item) stays quiet on Saturday and Sunday.
"""

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from backend.core.market_calendar import is_trading_day, last_trading_day
from backend.datalayer.bars import AFTER_CLOSE as BARS_READY, BARS
from backend.datalayer.news import COLLECTION as NEWS
from backend.datalayer.news_sources import FEEDS
from backend.engine.session import IST

SILENT_AFTER = timedelta(days=3)  # RBI, SEBI and PIB can go a weekend without a release
EXAMPLES = 8
# The 16:00 pass may hold its lock for two hours (scheduler.LOCK_TTL_MS).
PASS_DONE = time(18, 0)
# A loop's own run time counts toward its age (the quotes loop's Nifty 200
# pass takes tens of seconds); below this a 15-second loop would flap.
MIN_STALE_SECONDS = 120
BELLWETHERS = 5  # first names of the Nifty 200 the quotes loop always covers


def _names(symbols) -> str:
    symbols = sorted(symbols)
    more = f" +{len(symbols) - EXAMPLES}" if len(symbols) > EXAMPLES else ""
    return ", ".join(symbols[:EXAMPLES]) + more


def last_trading_day_at(now: datetime, at: time) -> date:
    """The latest weekday whose `at` (IST) is not after `now`."""
    local = now.astimezone(IST)
    day = local.date() if local.time() >= at else local.date() - timedelta(days=1)
    return last_trading_day(day)


def _text(value) -> Optional[str]:
    return value.decode() if isinstance(value, bytes) else value


async def _heartbeats(redis) -> list[str]:
    from backend.datalayer.worker import RENEW_SECONDS, _loops, heartbeat_ages

    ages = await heartbeat_ages(redis)
    failures = []
    for name, interval in [("leader", RENEW_SECONDS), *((loop.name, loop.interval_seconds) for loop in _loops())]:
        age = ages.get(name)
        if age is None:
            failures.append(f"Ingest loop {name} has not beaten recently (heartbeat expired)")
        elif age > max(2 * interval, MIN_STALE_SECONDS):
            failures.append(f"Ingest loop {name} last beat {age // 60} min ago")
    return failures


async def _quotes(redis) -> list[str]:
    from backend.factor.data import universe
    from backend.marks import QUOTE_KEY

    names = universe()[:BELLWETHERS]
    if not names or any(await redis.mget([QUOTE_KEY.format(s) for s in names])):
        return []
    return [f"Quotes loop failing: no cached quote for {', '.join(names)}"]


async def _last_pass(redis, now: datetime) -> list[str]:
    from backend.scheduler import LAST_PASS_KEY

    due = last_trading_day_at(now, PASS_DONE).isoformat()
    last = _text(await redis.get(LAST_PASS_KEY))
    return [] if last and last >= due else [f"Daily pass for {due} has not run (last: {last or 'never'})"]


async def _picks(db, now: datetime) -> list[str]:
    from backend.forecast.picks import STUDY

    due = last_trading_day_at(now, PASS_DONE)
    doc = await db[STUDY].find_one({"_id": "latest"}, {"as_of": 1})
    at = doc and doc.get("as_of")
    ran = at and (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).astimezone(IST).date()
    return [] if ran and ran >= due else [f"Picks job has not run for {due.isoformat()} (last: {ran or 'never'})"]


async def live(db, redis, now: Optional[datetime] = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    if redis is None:
        return await _picks(db, now)
    return [*await _heartbeats(redis), *await _quotes(redis), *await _last_pass(redis, now), *await _picks(db, now)]


async def check(db, redis=None, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    latest = {row["_id"]: row["date"] async for row in db[BARS].aggregate(
        [{"$group": {"_id": "$symbol", "date": {"$max": "$date"}}}])}
    newest = max(latest.values(), default=None)
    session = last_trading_day_at(now, BARS_READY).isoformat()
    stale = [s for s, d in latest.items() if d < session]

    universe = set()
    async for prefs in db["user_prefs"].find({}, {"universe": 1}):
        universe |= {s.upper().removesuffix(".NS") for s in prefs.get("universe") or []}
    listed = set(await db["instruments"].distinct(
        "tradingsymbol", {"exchange": "NSE", "tradingsymbol": {"$in": sorted(universe)}}))
    unlisted = universe - listed

    heard = set(await db[NEWS].distinct("feeds", {"fetched_at": {"$gte": now - SILENT_AFTER}}))
    silent = [name for name, *_ in FEEDS if name not in heard]

    failures = ([f"Stale bars: {len(stale)} symbol(s) behind {session} ({_names(stale)})"] if stale else [])
    failures += await live(db, redis, now)
    return {
        "bars_as_of": newest or "none",
        "stale_bars": len(stale), **({"stale": _names(stale)} if stale else {}),
        "unlisted_in_universes": len(unlisted), **({"unlisted": _names(unlisted)} if unlisted else {}),
        "silent_feeds": len(silent), **({"silent": _names(silent)} if silent else {}),
        "failures": failures,
    }


async def alerts(db, redis, now: Optional[datetime] = None) -> list[str]:
    """What the admin's Today shows: the live checks, plus the last nightly
    check's failures that are not live ones (stale bars). Quiet at weekends."""
    from backend.system.jobs import DATA_QUALITY, last_runs

    now = now or datetime.now(timezone.utc)
    if not is_trading_day(now.astimezone(IST).date()):
        return []
    out = await live(db, redis, now)
    run = (await last_runs(redis, [DATA_QUALITY]))[DATA_QUALITY] if redis is not None else None
    if run and not run["ok"]:
        try:
            nightly = json.loads(run["note"]).get("failures") or []
        except (ValueError, AttributeError):
            nightly = [f"Data-quality check failed: {run['note']}"]
        out += [f for f in nightly if f.startswith("Stale bars") or f.startswith("Data-quality")]
    return out
