"""Manual runs (a user's scan, an admin's gate backtest) go to the jobs process.

Each is minutes of work. Run inside the API, it shares the event loop with every
request and dies with an API restart. `submit` pushes it onto the Redis list
`jobs:queue` when the jobs process is beating (backend/jobs.py), and runs it here
as before when it is not, so a stopped jobs container never strands a run.

ponytail: BRPOP removes an item before it runs, so a jobs crash mid-run loses it
(as an API crash always did). Add a processing list if a lost run starts to matter.
"""

import asyncio
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

KEY = "jobs:queue"
ALIVE_SECONDS = 60  # jobs beats every 10 s; older than this, nobody would pop the item
CONCURRENT = 2  # minutes-long runs at once in the jobs process

_TASKS: set = set()  # strong refs, so a running job is not garbage-collected


async def _scan(db, redis, user_id: str, universe: list[str]) -> None:
    from backend.prefs import PrefsStore
    from backend.suggestions.scan import scan_universe
    from backend.suggestions.thesis import attach_theses

    prefs = await PrefsStore(db).get(user_id)
    created = await scan_universe(
        db, user_id=user_id, universe=universe,
        account_size=prefs["account_size"], max_exposure=prefs["max_exposure"],
        source="manual", redis=redis,
    )
    if created:
        await attach_theses(db, user_id, created)


async def _gate_backtest(db, redis, strategy_name: str) -> None:
    from backend.data.providers.yfinance_provider import YFinanceProvider
    from backend.engine.session import IST
    from backend.risk.gate_backtest import backtest_for_gate, intraday_history

    _, provider = await intraday_history(db, redis)
    await backtest_for_gate(db, strategy_name, provider or YFinanceProvider(), datetime.now(IST))


KINDS = {"scan": _scan, "gate_backtest": _gate_backtest}


async def _run(db, redis, kind: str, args: dict) -> None:
    handler = KINDS.get(kind)
    if handler is None:
        logger.warning("job queue: unknown kind %r dropped", kind)
        return
    try:
        await handler(db, redis, **args)
    except Exception:
        logger.exception("job %s %s failed", kind, args)


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def submit(db, redis, kind: str, **args) -> str:
    """'queued' when the jobs process takes it, 'local' when it runs in this process."""
    from backend.jobs import heartbeat_age

    try:
        age = await heartbeat_age(redis)
        if age is not None and age < ALIVE_SECONDS:
            await redis.lpush(KEY, json.dumps({"kind": kind, "args": args}))
            return "queued"
    except Exception as exc:
        logger.warning("job queue push of %s failed, running here: %s", kind, exc)
    _spawn(_run(db, redis, kind, args))
    return "local"


async def work_once(db, redis, gate: asyncio.Semaphore | None = None, timeout: int = 1) -> bool:
    """Pops one item and starts it; False when the queue stayed empty. With
    `gate`, it waits for a free slot before popping, so waiting items stay in Redis."""
    gate = gate or asyncio.Semaphore(1)
    await gate.acquire()
    started = False
    try:
        item = await redis.brpop(KEY, timeout=timeout)
        if item is None:
            return False
        try:
            payload = json.loads(item[1])
            kind, args = payload["kind"], payload.get("args") or {}
        except (TypeError, ValueError, KeyError):
            logger.warning("job queue: unreadable item %r dropped", item[1])
            return True

        async def run() -> None:
            try:
                await _run(db, redis, kind, args)
            finally:
                gate.release()

        _spawn(run())
        started = True
        return True
    finally:
        if not started:
            gate.release()


async def work_forever(db, redis) -> None:
    """The jobs process's consumer."""
    gate = asyncio.Semaphore(CONCURRENT)
    while True:
        try:
            await work_once(db, redis, gate, timeout=30)
        except Exception as exc:
            logger.warning("job queue pop failed: %s", exc)
            await asyncio.sleep(5)
