import json
from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage
from mongomock_motor import AsyncMongoMockClient

from backend.plan import revise, store
from backend.plan.validate import TradePlan
from backend.tests.test_ai_runner import _Script, _call
from backend.tests.test_datalayer_news import FakeRedis

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 6, 10, 30, tzinfo=IST)


async def _setup(positions=True):
    mongo, redis = AsyncMongoMockClient()["test_db"], FakeRedis()
    if positions:
        await mongo["paper_positions"].insert_one({"user_id": "alice", "symbol": "TCS", "quantity": 10,
                                                   "avg_price": 100.0, "venue": "paper"})
    plan = await store.save(mongo, redis, "alice", NOW.date(), TradePlan(
        trigger="pre_open", scope=["TCS", "INFY"], allow=[{"symbol": "TCS", "strategies": ["orb_breakout"]}]),
        NOW - timedelta(hours=1))
    return mongo, redis, plan


async def test_revision_uses_tools_and_keeps_exits():
    mongo, redis, plan = await _setup()
    llm = _Script(_call("news", {"symbol": "TCS"}), AIMessage(content=json.dumps(
        {"allow": [], "exits": [{"symbol": "TCS", "reason": "guidance cut"}], "rationale": ["Cut TCS."]})))
    doc = await revise.revise_plan(mongo, redis, "alice", plan, [("news:n1", "TCS guidance cut")], NOW, llm=llm)
    assert doc["version"] == 2 and doc["exits"] == [{"symbol": "TCS", "reason": "guidance cut"}]
    assert "INFY" in doc["scope"]


async def test_revision_without_positions_still_proceeds():
    mongo, redis, plan = await _setup(positions=False)
    llm = _Script(_call("positions", {}), AIMessage(content=json.dumps({"skip_day": True, "rationale": ["Event risk."]})))
    doc = await revise.revise_plan(mongo, redis, "alice", plan, [("event_passed", "CPI")], NOW, llm=llm)
    assert doc["skip_day"] is True and doc["trigger"] == "event_passed"
