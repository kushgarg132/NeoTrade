"""Daily intraday paper run, started without anyone pressing Start.

For every user with `auto_paper_intraday` on, one INTRADAY run is kept alive
from the 09:15 IST open to the 15:30 close on weekdays, then stopped (the
runner itself squares off MIS positions at 15:15). Checked once a minute on
every worker.

Which worker owns a user's run: a Redis key `autorun:{user_id}` holding that
worker's token, renewed every tick while its run is alive. Only a worker that
wins the key with SET NX starts a run, so two workers never both start one;
if the owner dies (a deploy), the key expires within KEY_TTL_MS and another
worker restarts the run. Mongo's run status is not used for this -- each
worker's startup marks every RUNNING row orphaned, including ones another
worker is still driving.

Not restarted the same day: a run the user stopped themselves during the
session, or once MAX_STARTS_PER_DAY auto runs have started (a crash loop).
"""

import asyncio
import logging
import uuid
from datetime import datetime, time, timezone
from typing import Optional

from backend.core.clock import SystemClock
from backend.engine.session import IST
from backend.prefs import PrefsStore
from backend.runs import ACTIVE, RunStore

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 60
KEY_TTL_MS = 150_000
MAX_STARTS_PER_DAY = 5
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
POLL_SECONDS = 60.0

# This process's identity for key ownership, and the auto runs it drives.
_TOKEN = str(uuid.uuid4())
_LOCAL: dict[str, str] = {}  # user_id -> run_id


def in_session(now: datetime) -> bool:
    # ponytail: weekdays only, no NSE holiday calendar. On a holiday the feed
    # delivers no new bars, so the run idles and places nothing.
    local = now.astimezone(IST)
    return local.weekday() < 5 and SESSION_OPEN <= local.time() < SESSION_CLOSE


def _key(user_id: str) -> str:
    return f"autorun:{user_id}"


async def _release(redis, user_id: str) -> None:
    if await redis.get(_key(user_id)) in (_TOKEN, _TOKEN.encode()):
        await redis.delete(_key(user_id))


async def _stop_local(redis, runs: RunStore, user_id: str) -> None:
    from backend.routers.trading import stop_background_run

    run_id = _LOCAL.pop(user_id, None)
    if run_id is not None:
        await stop_background_run(run_id)
        await runs.mark_stopped(run_id)
    await _release(redis, user_id)


async def _may_start(runs: RunStore, user_id: str, now: datetime) -> bool:
    day_start = datetime.combine(now.astimezone(IST).date(), time(0, 0), tzinfo=IST).astimezone(timezone.utc)
    today = await runs.collection.find({
        "user_id": user_id, "mode": "INTRADAY", "started_at": {"$gte": day_start},
    }).to_list(length=None)
    if any(r["status"] == ACTIVE and r["params"].get("origin") != "auto" for r in today):
        return False  # the user already started one by hand
    auto = [r for r in today if r["params"].get("origin") == "auto"]
    if any(r["status"] == "STOPPED" and r.get("error") is None for r in auto):
        return False  # the user stopped today's auto run themselves
    return len(auto) < MAX_STARTS_PER_DAY


async def tick(db, redis, now: Optional[datetime] = None, launch=None) -> dict:
    """One pass. `launch` defaults to routers.trading.launch_run; tests pass
    a stub. Returns what it did, for logs and tests."""
    from backend.routers import trading

    now = now or SystemClock().now()
    launch = launch or trading.launch_run
    runs = RunStore(db)
    done = {"started": [], "renewed": [], "stopped": []}
    if redis is None:
        return done

    enabled = {
        doc["user_id"] for doc in await db["user_prefs"].find({"auto_paper_intraday": True}).to_list(length=None)
    }

    if not in_session(now):
        for user_id in list(_LOCAL):
            await _stop_local(redis, runs, user_id)
            done["stopped"].append(user_id)
        return done

    for user_id in list(_LOCAL):
        if user_id not in enabled:  # turned off mid-session
            await _stop_local(redis, runs, user_id)
            done["stopped"].append(user_id)

    prefs_store = PrefsStore(db)
    for user_id in sorted(enabled):
        run_id = _LOCAL.get(user_id)
        if run_id is not None and run_id in trading._RUNS:
            await redis.set(_key(user_id), _TOKEN, xx=True, px=KEY_TTL_MS)
            done["renewed"].append(user_id)
            continue
        _LOCAL.pop(user_id, None)  # our run ended (stopped by the user, or crashed)
        await _release(redis, user_id)

        if not await _may_start(runs, user_id, now):
            continue
        if not await redis.set(_key(user_id), _TOKEN, nx=True, px=KEY_TTL_MS):
            continue  # another worker owns this user's run
        try:
            prefs = await prefs_store.get(user_id)
            _LOCAL[user_id] = await launch(
                user_id, "INTRADAY", prefs["universe"], POLL_SECONDS, runs, origin="auto",
            )
            done["started"].append(user_id)
        except Exception as exc:
            logger.exception("auto-run start failed for %s: %s", user_id, exc)
            await _release(redis, user_id)
    return done


async def autorun_loop(db, redis) -> None:
    while True:
        try:
            result = await tick(db, redis)
            if result["started"] or result["stopped"]:
                logger.info("auto-run: %s", result)
        except Exception as exc:
            logger.exception("auto-run tick failed: %s", exc)
        await asyncio.sleep(INTERVAL_SECONDS)


def start(db, redis) -> asyncio.Task:
    return asyncio.create_task(autorun_loop(db, redis))
