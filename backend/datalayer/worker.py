"""The ingest process: keeps the shared market, macro and news data fresh.

Runs in its own container (`ingest` in docker-compose.yml, same image as the
API) so slow fetches and LLM calls never share the API's event loop. API
workers only read what this writes, and fall back to fetching themselves
when it is missing or stale.

Exactly one instance works at a time: it holds `ingest:leader`, renewing it
every few seconds. A second instance (or the old container overlapping a
deploy) waits for the lock. A leader that loses the lock exits, and Docker's
restart policy brings it back as a waiter.

Each loop writes `ingest:heartbeat:{name}` (unix seconds) after every pass
that did not raise, which `/health` reports as an age.

    python -m backend.datalayer.worker
"""

import asyncio
import logging
import os
import time
from typing import Awaitable, Callable, NamedTuple

from backend import locks

logger = logging.getLogger(__name__)

LEADER_KEY = "ingest:leader"
LEADER_TTL_MS = 30_000
RENEW_SECONDS = 10
SHUTDOWN_SECONDS = 10  # max wait for loops and the lock release once leadership is lost
HEARTBEAT_KEY = "ingest:heartbeat:{}"
HEARTBEAT_TTL_SECONDS = 300


class Loop(NamedTuple):
    name: str
    interval_seconds: float
    run: Callable[[object, object], Awaitable[None]]  # (db, redis)


def _loops() -> list[Loop]:
    from backend.datalayer import accuracy, bars, market, news, outcomes, prices, reactor
    from backend.mine import events
    from backend.plan import revise

    return [
        Loop("quotes", 15, prices.quotes),
        Loop("macro", 60, prices.macro),
        Loop("news_poll", 60, news.poll_loop),
        Loop("news_process", news.PROCESS_SECONDS, news.process_loop),
        Loop("calendar", 6 * 3600, market.calendar),
        Loop("flows", 30 * 60, market.flows),
        Loop("regime", 60, market.regime),
        Loop("brief", 60, market.brief),
        Loop("news_react", 60, reactor.react),
        Loop("news_scan", 120, reactor.scan),
        Loop("news_exits", 60, reactor.shadow_exits),
        Loop("news_outcomes", 5 * 60, outcomes.loop),
        Loop("news_accuracy", 3600, accuracy.loop),  # builds once per 7 days
        Loop("bars", 15 * 60, bars.loop),
        Loop("fundamentals", 30 * 60, bars.fundamentals_loop),
        Loop("plan_revise", 60, revise.loop),
        Loop("corp_events", 6 * 3600, events.loop),
    ]


async def beat(redis, name: str, interval_seconds: float = 0) -> None:
    # Outlives the loop's own interval: a 30-minute loop read as dead after 5.
    ttl = max(HEARTBEAT_TTL_SECONDS, int(2 * interval_seconds))
    await redis.set(HEARTBEAT_KEY.format(name), str(int(time.time())), ex=ttl)


async def heartbeat_ages(redis) -> dict[str, int]:
    """Seconds since each loop last finished a pass. A loop missing here has
    not beaten in HEARTBEAT_TTL_SECONDS, or has never run."""
    now = int(time.time())
    prefix = HEARTBEAT_KEY.format("")
    ages = {}
    async for key in redis.scan_iter(match=prefix + "*"):
        value = await redis.get(key)
        if value is not None:
            ages[key[len(prefix):]] = now - int(value)
    return ages


async def _run_loop(db, redis, loop: Loop) -> None:
    while True:
        try:
            await loop.run(db, redis)
            await beat(redis, loop.name, loop.interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("ingest loop %s failed: %s", loop.name, exc)
        await asyncio.sleep(loop.interval_seconds)


async def run(db, redis, loops: list[Loop]) -> None:
    """Waits for leadership, then runs every loop until leadership is lost."""
    token = None
    while token is None:
        token = await locks.acquire(redis, LEADER_KEY, LEADER_TTL_MS)
        if token is None:
            await asyncio.sleep(RENEW_SECONDS)
    logger.info("ingest: leader, starting %d loop(s)", len(loops))

    tasks = [asyncio.create_task(_run_loop(db, redis, loop)) for loop in loops]
    try:
        while True:
            await beat(redis, "leader")
            await asyncio.sleep(RENEW_SECONDS)
            if not await locks.renew(redis, LEADER_KEY, token, LEADER_TTL_MS):
                logger.warning("ingest: lost leadership, stopping")
                return
    finally:
        for task in tasks:
            task.cancel()
        # Bounded: on 2026-10-15 some loops outlived their cancel, gather() never
        # returned, and the worker sat idle for days instead of exiting.
        await asyncio.wait(tasks, timeout=SHUTDOWN_SECONDS)
        try:
            await asyncio.wait_for(locks.release(redis, LEADER_KEY, token), SHUTDOWN_SECONDS)
        except Exception as exc:  # the TTL frees it anyway
            logger.warning("ingest: could not release leadership: %s", exc)


async def main() -> None:
    from backend.database import db

    await db.connect_to_database()
    try:
        await run(db.db, db.redis, _loops())
    finally:
        try:
            await asyncio.wait_for(db.close_database_connection(), SHUTDOWN_SECONDS)
        except Exception as exc:
            logger.warning("ingest: closing connections failed: %s", exc)
    # Only reached when leadership was lost: let Docker restart us. Exit hard, because
    # asyncio.run() on 3.11 waits forever for a to_thread call stuck in a blocking read,
    # which left the worker alive but idle (no news, quotes or plans) on 2026-10-08.
    logging.shutdown()
    os._exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs every request URL, bot tokens included
    from backend import log_redaction
    log_redaction.install()
    asyncio.run(main())
