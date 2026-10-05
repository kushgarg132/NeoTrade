"""Token-checked Redis locks: only the holder renews or releases.

The same shape as the scheduler's daily lock (backend/scheduler.py): a
SET NX with a random token, and a holder that compares the token before
touching the key, so a holder whose TTL expired can never delete or extend
a lock another process has since taken.
"""

import uuid
from typing import Optional


async def acquire(redis, key: str, ttl_ms: int) -> Optional[str]:
    """The lock's token, or None if someone else holds it."""
    token = uuid.uuid4().hex
    return token if await redis.set(key, token, nx=True, px=ttl_ms) else None


# ponytail: get-then-act is not atomic; a TTL expiring between the two calls
# lets a stale holder touch a fresh lock. Fine while TTL >> renew interval;
# switch to a Lua compare-and-set if a lock ever runs close to its TTL.
async def renew(redis, key: str, token: str, ttl_ms: int) -> bool:
    """Extends the lock if this token still holds it; False if it was lost."""
    if await redis.get(key) != token:
        return False
    return bool(await redis.set(key, token, xx=True, px=ttl_ms))


async def release(redis, key: str, token: str) -> None:
    if await redis.get(key) == token:
        await redis.delete(key)
