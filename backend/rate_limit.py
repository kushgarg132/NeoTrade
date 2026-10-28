"""Fixed-window per-user rate limits in Redis, for what costs money or compute
(LLM chat and analysis, background scans). Fails open: a Redis problem never
blocks the user."""

import logging

logger = logging.getLogger(__name__)


async def allow(redis, key: str, limit: int, window_seconds: int) -> bool:
    if redis is None:
        return True
    try:
        name = f"rate:{key}"
        # TTL first and in one command: if the process dies between the two
        # calls the key still expires, instead of counting up forever.
        await redis.set(name, 0, ex=window_seconds, nx=True)
        count = await redis.incr(name)
        return count <= limit
    except Exception as exc:
        logger.warning("rate limit check failed for %s: %s", key, exc)
        return True
