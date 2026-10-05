import json
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.plan import builder, store
from backend.tests.test_datalayer_news import FakeRedis

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 6, 8, 46, tzinfo=IST)


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


@pytest.fixture
async def setup(mongo):
    await mongo["user_prefs"].insert_one({"user_id": "alice", "universe": ["TCS", "INFY"]})
    redis = FakeRedis()
    await redis.set("market:regime", json.dumps({"label": "neutral", "score": 0.1, "drivers": ["flat"]}))
    return mongo, redis


def _fake(*replies):
    calls = []

    async def complete(system, prompt):
        calls.append(prompt)
        return replies[min(len(calls), len(replies)) - 1]
    return complete, calls


async def test_builds_validates_and_stores_a_pre_open_plan(setup):
    mongo, redis = setup
    complete, calls = _fake(json.dumps({"allow": [{"symbol": "TCS", "strategies": ["orb_breakout"]}],
                                        "risk_multiplier": 0.5, "rationale": ["x", "y"]}))
    doc = await builder.build_plan(mongo, redis, "alice", NOW, complete=complete)
    assert doc["version"] == 1 and doc["trigger"] == "pre_open" and doc["risk_multiplier"] == 0.5
    assert "orb_breakout" in calls[0] and "TCS" in calls[0] and "neutral" in calls[0]
    assert (await store.current(redis, "alice", NOW.date()))["risk_multiplier"] == 0.5


async def test_llm_error_twice_stores_the_fallback(setup):
    mongo, redis = setup
    complete, calls = _fake("Error generating response: 500")
    doc = await builder.build_plan(mongo, redis, "alice", NOW, complete=complete)
    assert doc["trigger"] == "fallback" and len(calls) == 2
    assert sorted(a["symbol"] for a in doc["allow"]) == ["INFY", "TCS"]


async def test_budget_exhausted_skips_the_call(setup, monkeypatch):
    mongo, redis = setup
    monkeypatch.setattr(store.settings, "PLAN_LLM_CALLS_PER_DAY", 0)
    complete, calls = _fake("{}")
    doc = await builder.build_plan(mongo, redis, "alice", NOW, complete=complete)
    assert calls == [] and doc["trigger"] == "fallback"


async def test_news_names_join_the_candidates(setup):
    mongo, redis = setup
    await mongo["news_items"].insert_one({
        "_id": "n1", "status": "SCORED", "title": "Axis Bank wins big deal",
        "published_at": NOW - timedelta(hours=10),
        "impacts": [{"type": "symbol", "target": "AXISBANK", "impact": 8, "direction": 0.8}]})
    complete, calls = _fake("{}")
    await builder.build_plan(mongo, redis, "alice", NOW, complete=complete)
    assert "AXISBANK" in calls[0] and "Axis Bank wins big deal" in calls[0]


async def test_each_attempt_spends_budget(setup):
    mongo, redis = setup
    complete, calls = _fake("Error generating response: 500")
    await builder.build_plan(mongo, redis, "alice", NOW, complete=complete)
    assert int(await redis.get(store.CALLS_KEY.format(NOW.date().isoformat()))) == 2
