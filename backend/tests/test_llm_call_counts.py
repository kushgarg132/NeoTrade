"""Every model hand-out is counted per feature per IST day (backend/llm.py::_count_call), and the
system status shows today's counts."""

import pytest

from backend import llm
from backend.tests.test_rotation import FakeRedis


class CountingRedis(FakeRedis):
    async def incr(self, key):
        self.values[key] = int(self.values.get(key) or 0) + 1
        return self.values[key]

    async def expire(self, key, seconds):
        return True


async def test_calls_are_counted_per_feature_and_unknown_ones_as_other(monkeypatch):
    from backend.database import db

    redis = CountingRedis()
    monkeypatch.setattr(db, "redis", redis)
    await llm._count_call("chat")
    await llm._count_call("chat")
    await llm._count_call("mystery")
    await llm._count_call(None)
    counts = {k.split(":")[2]: v for k, v in redis.values.items()}
    assert counts == {"chat": 2, "other": 2}


async def test_a_redis_failure_never_blocks_a_call(monkeypatch):
    from backend.database import db

    class Broken:
        async def incr(self, key):
            raise ConnectionError("down")
    monkeypatch.setattr(db, "redis", Broken())
    await llm._count_call("news")  # no raise


def test_calls_key_names_the_feature_and_day():
    assert llm.calls_key("news", "2026-11-02") == "llm:calls:news:2026-11-02"
    assert llm.calls_key("weird", "2026-11-02") == "llm:calls:other:2026-11-02"
