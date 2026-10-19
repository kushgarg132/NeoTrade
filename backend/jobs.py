"""The jobs process: the background loops that used to start inside the API.

Runs in its own container (`jobs` in docker-compose.yml, same image, no port).
The loops keep their own Redis locks (scheduler:daily_lock, guardrails:tick,
the Telegram poll lock, per-user autorun locks), so this adds no leader rule:
a second instance, or an API that still has RUN_BACKGROUND_JOBS on, is as
safe as the second uvicorn worker always was. It writes `jobs:heartbeat`,
which `/health` reports as an age.

Stays in the API: the ws price pump and the ws:events / runs:cancel listener
(they need the socket hub).

    python -m backend.jobs
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "jobs:heartbeat"
HEARTBEAT_TTL_SECONDS = 60
BEAT_SECONDS = 10


def start_loops(db, redis) -> list[str]:
    """Starts every background loop and returns their names. Shared by the
    API (flag on) and `main`, so the two cannot drift."""
    from backend import scheduler
    from backend.engine import autorun
    from backend.engine import sweeps as order_sweeps
    from backend.guardrails import monitor as guardrail_monitor
    from backend.guardrails import telegram_bot

    scheduler.start(db, redis)  # 16:00 daily pass, 09:20 catch-up
    order_sweeps.start(db)  # stuck approvals and late live fills
    guardrail_monitor.start(db, redis)  # the user's limits against their broker
    telegram_bot.start(db, redis)  # inbound polling, not a webhook
    autorun.start(db, redis)  # daily intraday paper run and the morning pass
    return ["scheduler", "order_sweeps", "guardrail_monitor", "telegram_bot", "autorun"]


async def heartbeat_age(redis) -> int | None:
    """Seconds since the jobs process last beat; None when it is not running."""
    value = await redis.get(HEARTBEAT_KEY) if redis is not None else None
    return None if value is None else int(time.time()) - int(value)


async def _beat(redis) -> None:
    while True:
        if redis is not None:
            try:
                await redis.set(HEARTBEAT_KEY, str(int(time.time())), ex=HEARTBEAT_TTL_SECONDS)
            except Exception as exc:
                logger.warning("jobs heartbeat failed: %s", exc)
        await asyncio.sleep(BEAT_SECONDS)


async def main() -> None:
    from backend import broadcast
    from backend.app_settings import AppSettingsStore
    from backend.configs.settings import require_jwt_secret
    from backend.database import db
    from backend.routers.trading import handle_cancel_broadcast
    from backend.runs import RunStore, keep_alive

    require_jwt_secret()
    await db.connect_to_database()
    await AppSettingsStore(db.db).load_into_cache()
    # Autorun starts runs in this process, so it needs what the API has for its own:
    # the alive key (so no sweep orphans them), the orphan sweep, and the cancel channel.
    _tasks = [  # strong refs
        asyncio.create_task(broadcast.listen_forever(db.redis, {"runs:cancel": handle_cancel_broadcast})),
        asyncio.create_task(keep_alive(db.redis)),
    ]
    runs = RunStore(db.db)
    await runs.ensure_indexes()
    await runs.close_orphaned(db.redis)
    names = start_loops(db.db, db.redis)
    logger.info("jobs: started %s", ", ".join(names))
    await _beat(db.redis)


if __name__ == "__main__":
    from backend import log_redaction
    from backend.configs.logging_config import setup_logging

    setup_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs every request URL, bot tokens included
    log_redaction.install()
    asyncio.run(main())
