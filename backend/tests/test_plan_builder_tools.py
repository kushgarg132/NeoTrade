import json
from datetime import datetime, timedelta, timezone

import pytest
from langchain_core.messages import AIMessage
from mongomock_motor import AsyncMongoMockClient

from backend.ai import grounding
from backend.plan import builder, store
from backend.tests.test_ai_runner import _Script, _call
from backend.tests.test_datalayer_news import FakeRedis

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 6, 8, 46, tzinfo=IST)


@pytest.fixture
async def world():
    mongo, redis = AsyncMongoMockClient()["test_db"], FakeRedis()
    await mongo["user_prefs"].insert_one({"user_id": "alice", "universe": ["TCS", "INFY"]})
    await redis.set("market:regime", json.dumps({"label": "neutral", "score": 0.1, "drivers": ["flat"]}))
    return mongo, redis


def _plan_json(**kw):
    return json.dumps({"allow": [{"symbol": "TCS", "strategies": ["orb_breakout"]}], "risk_multiplier": 0.8,
                       "rationale": ["Regime neutral at +0.10."], **kw})


async def test_builder_uses_tools_then_validates_and_stores(world):
    mongo, redis = world
    llm = _Script(_call("news", {"symbol": "AXISBANK"}), AIMessage(content=_plan_json()))
    doc = await builder.build_plan(mongo, redis, "alice", NOW, llm=llm)
    assert doc["trigger"] == "pre_open" and doc["risk_multiplier"] == 0.8
    assert doc["rationale"] == ["Regime neutral at +0.10."]
    assert int(await redis.get(store.CALLS_KEY.format(NOW.date().isoformat()))) == 2
    assert "Axis" not in llm.seen[0][1].content  # news is fetched by tool, not pre-stuffed


async def test_unsupported_rationale_lines_are_dropped(world):
    mongo, redis = world
    llm = _Script(AIMessage(content=_plan_json(rationale=["Crude at $150 hits OMCs.", "Regime neutral at +0.10."])))
    doc = await builder.build_plan(mongo, redis, "alice", NOW, llm=llm)
    assert doc["rationale"] == ["Regime neutral at +0.10."]


async def test_invalid_tool_reply_falls_back_to_single_call(world, monkeypatch):
    mongo, redis = world
    calls = []

    async def single(system, prompt):
        calls.append(prompt)
        return _plan_json(risk_multiplier=0.5)
    monkeypatch.setattr(builder, "_llm", single)
    llm = _Script(AIMessage(content="no json here"), AIMessage(content="still none"))
    doc = await builder.build_plan(mongo, redis, "alice", NOW, llm=llm)
    assert len(calls) == 1 and doc["risk_multiplier"] == 0.5 and doc["trigger"] == "pre_open"


async def test_tools_off_uses_single_call(world, monkeypatch):
    mongo, redis = world
    from backend.configs.settings import settings

    monkeypatch.setattr(settings, "AI_TOOLS_ENABLED", False)
    calls = []

    async def single(system, prompt):
        calls.append(prompt)
        return _plan_json()
    monkeypatch.setattr(builder, "_llm", single)
    llm = _Script()
    await builder.build_plan(mongo, redis, "alice", NOW, llm=llm)
    assert len(calls) == 1 and llm.seen == []


def test_numbers_in_reads_numbers_inside_text():
    assert 0.1 in grounding.numbers_in(["neutral (+0.10): flat", {"x": "FII -1,200 cr"}])
    assert 1200.0 in grounding.numbers_in([{"x": "FII -1,200 cr"}])


async def test_spent_budget_stops_the_tool_path_and_stores_the_fallback(world, monkeypatch):
    mongo, redis = world
    monkeypatch.setattr(store.settings, "PLAN_LLM_CALLS_PER_DAY", 0)
    llm = _Script(AIMessage(content=_plan_json()))
    doc = await builder.build_plan(mongo, redis, "alice", NOW, llm=llm)
    assert llm.seen == [] and doc["trigger"] == "fallback"


async def test_empty_or_schema_echo_reply_is_unusable(world, monkeypatch):
    mongo, redis = world

    async def single(system, prompt):
        return "not json"
    monkeypatch.setattr(builder, "_llm", single)
    llm = _Script(AIMessage(content="{}"))
    doc = await builder.build_plan(mongo, redis, "alice", NOW, llm=llm)
    assert doc["trigger"] == "fallback"


async def test_an_entirely_unsupported_rationale_is_stored_empty(world):
    mongo, redis = world
    llm = _Script(AIMessage(content=_plan_json(rationale=["Crude at $150.", "Brent up 9.9%."])))
    doc = await builder.build_plan(mongo, redis, "alice", NOW, llm=llm)
    assert doc["trigger"] == "pre_open" and doc["rationale"] == []
