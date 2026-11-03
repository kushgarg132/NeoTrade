from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.ai.facts import FACTS
from backend.ai.facts import user as facts
from backend.tests.test_datalayer_news import FakeRedis

USER = {"portfolio", "positions", "strategy_library", "learning", "journal"}


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
    alice = await facts.positions(mongo, redis, "alice")
    assert [p["symbol"] for p in alice["positions"]] == ["TCS"]


async def test_portfolio_without_snapshot_is_an_error_dict(mongo):
    out = await facts.portfolio(mongo, FakeRedis(), "alice")
    assert "error" in out and out["as_of"]


async def test_portfolio_as_of_is_the_snapshot_time_not_now(mongo):
    then = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    await mongo["portfolio_snapshots"].insert_one({"user_id": "alice", "at": then, "holdings": [], "totals": {}})
    out = await facts.portfolio(mongo, FakeRedis(), "alice")
    assert str(out["as_of"]).startswith("2026-10-01")


def test_user_tools_need_a_user():
    from backend.ai.facts import as_tools

    with pytest.raises(ValueError):
        as_tools(None, None, None, ["portfolio"])
