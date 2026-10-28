"""get_cached_sentiment must never block on the LLM -- a cache miss returns
None immediately (backend.ai.sentiment), never raises."""

from unittest.mock import AsyncMock

import pytest

from backend.ai.sentiment import get_cached_sentiment


async def test_cache_miss_returns_none_without_raising():
    redis = AsyncMock()
    redis.get.return_value = None
    result = await get_cached_sentiment("RELIANCE", redis)
    assert result is None
    redis.get.assert_awaited_once_with("sentiment:RELIANCE")


async def test_cache_hit_returns_float():
    redis = AsyncMock()
    redis.get.return_value = "0.42"
    result = await get_cached_sentiment("RELIANCE", redis)
    assert result == pytest.approx(0.42)


async def test_a_redis_connection_failure_returns_none_without_raising():
    """A DNS failure, a dropped connection, an Upstash outage -- none of it
    may reach the caller. score_intent already treats None as neutral; that
    is the entire reason this function exists, and a raised exception here
    used to take the whole engine loop (and every scan) down with it."""
    redis = AsyncMock()
    redis.get.side_effect = OSError("Name or service not known")

    result = await get_cached_sentiment("RELIANCE", redis)

    assert result is None


@pytest.mark.parametrize("raw,expected", [("nan", None), ("inf", None), ("junk", None), ("2.5", 1.0), ("-9", -1.0)])
async def test_bad_cached_values_are_none_or_clamped(raw, expected):
    redis = AsyncMock()
    redis.get.return_value = raw
    assert await get_cached_sentiment("RELIANCE", redis) == expected
