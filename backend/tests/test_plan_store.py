from datetime import date, datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import DuplicateKeyError

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


class _RacingColl:
    """Fails the first `fails` inserts with a duplicate key, as a racing writer's would."""

    def __init__(self, coll, fails):
        self.coll, self.fails = coll, fails

    def __getattr__(self, name):
        return getattr(self.coll, name)

    async def insert_one(self, doc):
        if self.fails:
            self.fails -= 1
            await self.coll.insert_one({**doc, "_id": "racer"})  # the other writer took this version
            raise DuplicateKeyError("dup")
        return await self.coll.insert_one(doc)


class _Db:
    def __init__(self, db, fails):
        self.coll = _RacingColl(db[store.COLLECTION], fails)

    def __getitem__(self, name):
        return self.coll


async def test_save_retries_once_on_a_duplicate_version(mongo):
    saved = await store.save(_Db(mongo, 1), FakeRedis(), "alice", DAY, TradePlan(trigger="pre_open"), NOW)
    assert saved["version"] == 2  # version 1 went to the racer


async def test_save_raises_when_the_retry_also_collides(mongo):
    with pytest.raises(DuplicateKeyError):
        await store.save(_Db(mongo, 2), FakeRedis(), "alice", DAY, TradePlan(trigger="pre_open"), NOW)
