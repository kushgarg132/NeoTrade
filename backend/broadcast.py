"""Cross-worker event bus: a thin wrapper over Redis pub/sub.

Two Uvicorn workers behind --workers N share nothing in-process. This is how
one worker's WS fan-out (backend/ws/hub.py) and run cancellation
(backend/routers/trading.py) reach the other. When `redis` is None (tests,
local dev without Redis) both functions degrade instead of crashing:
`publish` no-ops and `listen` returns immediately -- callers fall back to
whatever direct/local behavior they had before this module existed, the
same "degrade, don't crash" posture backend/ai/analyst_verdict.py's
get_cached_verdict already established for a missing cache.
"""

import json
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


async def publish(redis, channel: str, payload: dict) -> bool:
    """Returns True only if the message actually reached Redis. Callers that
    have a local fallback (backend/ws/hub.py's Hub.publish) must use this to
    decide whether to fall back -- `redis` being non-None only means a
    client object exists, not that it's actually reachable right now."""
    if redis is None:
        return False
    try:
        await redis.publish(channel, json.dumps(payload))
        return True
    except Exception as exc:
        logger.warning("broadcast publish to %s failed: %s", channel, exc)
        return False


async def listen(redis, handlers: dict[str, Callable[[dict], Awaitable[None]]]) -> None:
    """Subscribes once to every channel in `handlers` and dispatches each
    received message to the handler registered for its channel. Runs
    forever -- start it as a background asyncio.Task. Returns immediately,
    doing nothing, if `redis` is None."""
    if redis is None:
        return

    pubsub = redis.pubsub()
    await pubsub.subscribe(*handlers.keys())
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            handler = handlers.get(message["channel"])
            if handler is None:
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, ValueError):
                logger.warning("broadcast message on %s was not valid JSON", message["channel"])
                continue
            try:
                await handler(payload)
            except Exception as exc:
                logger.exception("broadcast handler for %s failed: %s", message["channel"], exc)
    finally:
        await pubsub.close()
