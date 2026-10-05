"""A per-user budget on what costs money or compute: each chat or analysis
message started an LLM task and each scan a background job, with no cap."""

from backend.rate_limit import allow


class _Redis:
    def __init__(self):
        self.counts, self.ttls = {}, {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, seconds):
        self.ttls[key] = seconds


async def test_allows_up_to_the_limit_then_refuses():
    redis = _Redis()
    results = [await allow(redis, "chat:alice", limit=3, window_seconds=60) for _ in range(4)]
    assert results == [True, True, True, False]
    assert redis.ttls["rate:chat:alice"] == 60


async def test_users_have_separate_budgets():
    redis = _Redis()
    for _ in range(3):
        await allow(redis, "chat:alice", limit=3, window_seconds=60)
    assert await allow(redis, "chat:bob", limit=3, window_seconds=60) is True


async def test_no_redis_means_no_limit():
    assert await allow(None, "chat:alice", limit=0, window_seconds=60) is True


async def test_a_redis_failure_never_blocks_the_user():
    class _Broken:
        async def incr(self, key):
            raise ConnectionError("redis down")

    assert await allow(_Broken(), "chat:alice", limit=1, window_seconds=60) is True
