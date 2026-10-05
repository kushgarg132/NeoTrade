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
        count = await redis.incr(name)
        if count == 1:
            await redis.expire(name, window_seconds)
        return count <= limit
    except Exception as exc:
        logger.warning("rate limit check failed for %s: %s", key, exc)
        return True
