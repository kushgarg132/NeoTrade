from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.ai.facts import FACTS
from backend.ai.facts import user as facts
from backend.engine.session import IST
from backend.plan import store
from backend.plan.validate import TradePlan
from backend.tests.test_datalayer_news import FakeRedis

USER = {"portfolio", "positions", "strategy_library", "game_plan", "learning", "journal"}


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


def test_user_facts_are_registered_as_user_facts():
    assert USER <= set(FACTS) and all(FACTS[n].user for n in USER)


async def test_user_facts_are_scoped_to_the_user_id(mongo):
    redis = FakeRedis()
    await mongo["paper_positions"].insert_many([
        {"user_id": "alice", "symbol": "TCS", "quantity": 10, "avg_price": 100.0, "venue": "paper"},
        {"user_id": "bob", "symbol": "INFY", "quantity": 5, "avg_price": 50.0, "venue": "paper"},
    ])
    now = datetime.now(timezone.utc)
    await store.save(mongo, redis, "bob", now.astimezone(IST).date(), TradePlan(trigger="pre_open"), now)
    alice = await facts.positions(mongo, redis, "alice")
    assert [p["symbol"] for p in alice["positions"]] == ["TCS"]
    assert (await facts.game_plan(mongo, redis, "alice"))["plan"] is None
    assert (await facts.game_plan(mongo, redis, "bob"))["plan"]["trigger"] == "pre_open"


async def test_portfolio_without_snapshot_is_an_error_dict(mongo):
    out = await facts.portfolio(mongo, FakeRedis(), "alice")
    assert "error" in out and out["as_of"]


async def test_game_plan_lists_versions(mongo):
    redis = FakeRedis()
    now = datetime.now(timezone.utc)
    day = now.astimezone(IST).date()
    await store.save(mongo, redis, "alice", day, TradePlan(trigger="pre_open", rationale=["a"]), now)
    await store.save(mongo, redis, "alice", day, TradePlan(trigger="regime_flip", rationale=["b"]), now)
    out = await facts.game_plan(mongo, redis, "alice")
    assert [v["trigger"] for v in out["versions"]] == ["pre_open", "regime_flip"]
