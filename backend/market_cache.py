"""Stale-while-revalidate cache for the home page's market feeds (indices,
movers, headlines). Each feed takes seconds to fetch from Yahoo or Google
News; the page should not. A cached value is served at once whatever its
age, and one that is past its TTL is refreshed in the background, so only
the very first request after an empty cache waits.

Kept in Redis when there is one, so both uvicorn workers and a restarted
deploy share it; in memory otherwise (tests, local runs). A Redis flag
stops both workers refreshing the same feed at once.
"""

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

_local: dict[str, dict] = {}
_tasks: set[asyncio.Task] = set()
REFRESH_LOCK_SECONDS = 60


def _redis():
    from backend.database import db
    return db.redis


async def _read(key: str):
    redis = _redis()
    if redis is None:
        return _local.get(key)
    try:
        raw = await redis.get(f"market:{key}")
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("market cache read failed for %s: %s", key, exc)
        return _local.get(key)


async def _refresh(key: str, fetch: Callable[[], Awaitable]):
    data = await fetch()
    if not data:
        return data  # an empty answer (source down) is served but never cached
    entry = {"at": time.time(), "data": data}
    _local[key] = entry
    redis = _redis()
    if redis is not None:
        try:
            await redis.set(f"market:{key}", json.dumps(entry, default=str))
        except Exception as exc:
            logger.warning("market cache write failed for %s: %s", key, exc)
    return data


async def cached(key: str, ttl: float, fetch: Callable[[], Awaitable]):
    entry = await _read(key)
    if entry is None:
        return await _refresh(key, fetch)
    if time.time() - entry["at"] > ttl and await _claim(key):
        task = asyncio.create_task(_refresh_quietly(key, fetch))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return entry["data"]


async def _claim(key: str) -> bool:
    redis = _redis()
    if redis is None:
        return True
    try:
        return bool(await redis.set(f"market:{key}:refreshing", "1", nx=True, ex=REFRESH_LOCK_SECONDS))
    except Exception:
        return True


async def _refresh_quietly(key: str, fetch):
    try:
        await _refresh(key, fetch)
    except Exception as exc:
        logger.warning("market cache refresh failed for %s: %s", key, exc)
