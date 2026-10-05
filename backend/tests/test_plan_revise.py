import json
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.plan import revise, store
from backend.plan.validate import TradePlan
from backend.tests.test_datalayer_news import FakeRedis

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 6, 10, 30, tzinfo=IST)
DAY = NOW.date()


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


async def _plan(db, redis, user="alice", at=NOW - timedelta(minutes=60), trigger="pre_open", **kw):
    plan = TradePlan(trigger=trigger, scope=["TCS", "INFY"], allow=[{"symbol": "TCS", "strategies": ["orb_breakout"]}],
                     rationale=["calm"], **kw)
    return await store.save(db, redis, user, DAY, plan, at)


def _item(i, target, kind="symbol", impact=8, direction=-0.7):
    return {"_id": i, "status": "SCORED", "material": True, "title": f"headline {i}",
            "scored_at": (NOW - timedelta(minutes=1)).astimezone(timezone.utc),
            "published_at": (NOW - timedelta(minutes=30)).astimezone(timezone.utc),
            "impacts": [{"type": kind, "target": target, "impact": impact, "direction": direction}]}


async def test_material_news_on_a_planned_name_triggers_once_per_user(mongo):
    redis = FakeRedis()
    plans = {"alice": await _plan(mongo, redis)}
    await mongo["news_items"].insert_many([_item("n1", "TCS"), _item("n2", "INFY"), _item("n3", "WIPRO")])
    result = await revise.triggers(mongo, redis, plans, NOW)
    assert list(result) == ["alice"] and [code for code, _ in result["alice"]] == ["news:n1", "news:n2"]
    assert await revise.triggers(mongo, redis, plans, NOW) == {}  # claimed once


async def test_sector_news_reaches_names_in_that_sector(mongo):
    redis = FakeRedis()
    plans = {"alice": await _plan(mongo, redis)}
    await mongo["news_items"].insert_one(_item("s1", "Information Technology", kind="sector"))
    assert [c for c, _ in (await revise.triggers(mongo, redis, plans, NOW))["alice"]] == ["news:s1"]


async def test_regime_flip_triggers_and_first_label_only_records(mongo):
    redis = FakeRedis()
    plans = {"alice": await _plan(mongo, redis)}
    assert await revise.triggers(mongo, redis, plans, NOW) == {}
    await redis.set("market:regime", json.dumps({"label": "neutral"}))
    assert await revise.triggers(mongo, redis, plans, NOW) == {}
    await redis.set("market:regime", json.dumps({"label": "risk_off"}))
    assert [c for c, _ in (await revise.triggers(mongo, redis, plans, NOW))["alice"]] == ["regime_flip"]


async def test_passed_event_triggers_once(mongo):
    redis = FakeRedis()
    plans = {"alice": await _plan(mongo, redis)}
    await mongo["econ_calendar"].insert_one({"_id": "e1", "impact": "High", "country": "USD", "title": "CPI",
                                             "at": (NOW - timedelta(minutes=8)).astimezone(timezone.utc)})
    assert [c for c, _ in (await revise.triggers(mongo, redis, plans, NOW))["alice"]] == ["event_passed"]
    assert await revise.triggers(mongo, redis, plans, NOW) == {}


async def test_limits_cap_and_gap(mongo):
    redis = FakeRedis()
    await _plan(mongo, redis, at=NOW - timedelta(minutes=20))
    assert await revise.may_revise(mongo, "alice", DAY, NOW)
    await _plan(mongo, redis, at=NOW - timedelta(minutes=10), trigger="news:x")
    assert not await revise.may_revise(mongo, "alice", DAY, NOW)  # 10 min since the last version
    for k in range(5):
        await _plan(mongo, redis, at=NOW - timedelta(minutes=200), trigger=f"news:{k}")
    assert not await revise.may_revise(mongo, "alice", DAY, NOW + timedelta(hours=1))  # 6 revisions today


async def test_revise_plan_stores_a_new_version_with_exits(mongo):
    redis = FakeRedis()
    plan = await _plan(mongo, redis)

    async def complete(system, prompt):
        assert "guidance cut" in prompt and "orb_breakout" in prompt
        return json.dumps({"allow": [], "exits": [{"symbol": "TCS", "reason": "guidance cut"}],
                           "risk_multiplier": 0.5, "rationale": ["cut TCS"]})
    doc = await revise.revise_plan(mongo, redis, "alice", plan, [("news:n1", "TCS guidance cut")], NOW, complete)
    assert doc["version"] == 2 and doc["trigger"] == "news:n1"
    assert doc["exits"] == [{"symbol": "TCS", "reason": "guidance cut"}] and doc["scope"] == ["INFY", "TCS"]


async def test_unusable_reply_keeps_the_current_plan(mongo):
    redis = FakeRedis()
    plan = await _plan(mongo, redis)

    async def complete(system, prompt):
        return "Error generating response: 500"
    assert await revise.revise_plan(mongo, redis, "alice", plan, [("regime_flip", "x")], NOW, complete) is None
    assert (await store.current(redis, "alice", DAY))["version"] == 1


async def test_loop_skips_fallback_plans_and_outside_session(mongo, monkeypatch):
    redis = FakeRedis()
    await _plan(mongo, redis, user="alice", trigger="fallback")
    await mongo["news_items"].insert_one(_item("n1", "TCS"))
    called = []

    async def fake_revise(*args, **kw):
        called.append(args[2])
    monkeypatch.setattr(revise, "revise_plan", fake_revise)
    assert await revise.loop(mongo, redis, now=NOW) == 0
    await _plan(mongo, redis, user="bob")
    assert await revise.loop(mongo, redis, now=NOW.replace(hour=16)) == 0
    assert called == []


async def test_a_dropped_add_stays_in_scope_so_it_stays_gated(mongo):
    redis = FakeRedis()
    plan = await _plan(mongo, redis, add_symbols=["AXISBANK"])
    plan["scope"] = ["AXISBANK", "INFY", "TCS"]

    async def complete(system, prompt):
        return json.dumps({"allow": [{"symbol": "TCS", "strategies": ["orb_breakout"]}], "add_symbols": []})
    doc = await revise.revise_plan(mongo, redis, "alice", plan, [("regime_flip", "x")], NOW, complete)
    assert "AXISBANK" in doc["scope"] and doc["add_symbols"] == []
