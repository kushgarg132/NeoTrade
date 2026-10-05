from datetime import date, datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.plan import store
from backend.plan.validate import TradePlan
from backend.tests.test_datalayer_news import FakeRedis

DAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 3, 15, tzinfo=timezone.utc)


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


async def test_save_versions_and_mirrors_to_redis(mongo):
    redis = FakeRedis()
    first = await store.save(mongo, redis, "alice", DAY, TradePlan(trigger="pre_open", risk_multiplier=0.5), NOW)
    second = await store.save(mongo, redis, "alice", DAY, TradePlan(trigger="regime_flip"), NOW)
    assert (first["version"], second["version"]) == (1, 2)
    current = await store.current(redis, "alice", DAY)
    assert current["version"] == 2 and current["trigger"] == "regime_flip"
    assert [v["version"] for v in await store.versions(mongo, "alice", DAY)] == [1, 2]
    assert await store.current(redis, "bob", DAY) is None


async def test_budget_stops_at_the_cap(monkeypatch):
    monkeypatch.setattr(store.settings, "PLAN_LLM_CALLS_PER_DAY", 2)
    redis = FakeRedis()
    assert [await store.reserve_call(redis, DAY) for _ in range(3)] == [True, True, False]
    assert int(await redis.get(store.CALLS_KEY.format(DAY.isoformat()))) == 2
