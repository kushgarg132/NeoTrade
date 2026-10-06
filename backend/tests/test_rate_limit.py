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


async def test_a_user_has_a_daily_llm_ceiling_on_chat_and_research_only(monkeypatch):
    """Phase 17.2.7: each call made inside a user's request counts against
    USER_LLM_CALLS_PER_DAY; the shared pipeline (no user) and other features
    never do, and a cache hit never reaches the LLM so never counts."""
    import pytest
    from backend import llm
    from backend.database import db

    redis = _Redis()
    monkeypatch.setattr(db, "redis", redis)
    monkeypatch.setattr(llm.settings, "USER_LLM_CALLS_PER_DAY", 2)
    monkeypatch.setattr(llm.llm_service, "keys", [])  # no gateway: get_llm stops after the charge

    with llm.use_model(None, user_id="alice"):
        await llm.llm_service.get_llm(tier="deep", feature="chat")
        await llm.llm_service.get_llm(tier="fast", feature="research")
        await llm.llm_service.get_llm(tier="deep", feature="news")  # not a per-user feature
        with pytest.raises(llm.DailyLimitReached):
            await llm.llm_service.get_completion("q", system_prompt="s", tier="fast", feature="chat")
    with llm.use_model(None, user_id="bob"):
        await llm.llm_service.get_llm(tier="deep", feature="chat")
    for _ in range(5):
        await llm.llm_service.get_llm(tier="deep", feature="chat")  # no user: the shared pipeline
    assert sorted(redis.counts.values()) == [1, 3]
