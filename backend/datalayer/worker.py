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
import time
from typing import Awaitable, Callable, NamedTuple

from backend import locks

logger = logging.getLogger(__name__)

LEADER_KEY = "ingest:leader"
LEADER_TTL_MS = 30_000
RENEW_SECONDS = 10
HEARTBEAT_KEY = "ingest:heartbeat:{}"
HEARTBEAT_TTL_SECONDS = 300


class Loop(NamedTuple):
    name: str
    interval_seconds: float
    run: Callable[[object, object], Awaitable[None]]  # (db, redis)


def _loops() -> list[Loop]:
    from backend.datalayer import prices

    return [
        Loop("quotes", 15, prices.quotes),
        Loop("macro", 60, prices.macro),
    ]


async def beat(redis, name: str) -> None:
    await redis.set(HEARTBEAT_KEY.format(name), str(int(time.time())), ex=HEARTBEAT_TTL_SECONDS)


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
            await beat(redis, loop.name)
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
        await asyncio.gather(*tasks, return_exceptions=True)
        await locks.release(redis, LEADER_KEY, token)


async def main() -> None:
    from backend.database import db

    await db.connect_to_database()
    try:
        await run(db.db, db.redis, _loops())
    finally:
        await db.close_database_connection()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
    raise SystemExit(1)  # only reached when leadership was lost: let Docker restart us
