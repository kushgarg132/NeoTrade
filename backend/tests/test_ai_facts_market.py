import json
from datetime import date, datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.ai.facts import FACTS, as_tools
from backend.ai.facts import market
from backend.datalayer import bars
from backend.tests.test_datalayer_news import FakeRedis

MARKET = {"quote", "price_summary", "fundamentals", "news", "sentiment", "market_backdrop", "calendar"}


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


async def _bars(db, symbol="TCS", n=250, start=100.0, step=1.0):
    today = bars.today_ist()
    docs = []
    for i in range(n):
        day = today - timedelta(days=n - 1 - i)
        close = start + step * i
        docs.append({"symbol": symbol, "date": day.isoformat(), "open": close, "high": close + 1, "low": close - 1,
                     "close": close, "volume": 1000.0})
    await db[bars.BARS].insert_many(docs)


def test_registry_lists_every_market_fact_and_builds_tools():
    assert MARKET <= set(FACTS)
    tools = as_tools(None, None, "alice", sorted(MARKET))
    assert sorted(t.name for t in tools) == sorted(MARKET)


async def test_price_summary_from_daily_bars(mongo):
    await _bars(mongo)
    out = await market.price_summary(mongo, None, None, symbol="TCS")
    assert out["last_close"] == 349.0 and out["bars"] >= 200
    assert out["ret_20d"] == pytest.approx((349 / 329 - 1) * 100, abs=0.01)
    assert out["sma_200"] is not None and out["as_of"] and out["source"]


async def test_unknown_symbol_returns_an_error_not_an_exception(mongo):
    redis = FakeRedis()
    for fn in (market.price_summary, market.fundamentals):
        out = await fn(mongo, redis, None, symbol="NOPE")
        assert "error" in out and out["as_of"]


async def test_news_filters_and_trims_impacts(mongo):
    now = datetime.now(timezone.utc)
    await mongo["news_items"].insert_many([
        {"_id": "a", "status": "SCORED", "title": "TCS wins deal", "published_at": now - timedelta(hours=2),
         "scope": "COMPANY", "material": True, "url": "u",
         "impacts": [{"type": "symbol", "target": "TCS", "impact": 7, "direction": 0.6},
                     {"type": "symbol", "target": "INFY", "impact": 3, "direction": -0.2}]},
        {"_id": "b", "status": "SCORED", "title": "Old", "published_at": now - timedelta(days=5),
         "scope": "COMPANY", "impacts": [{"type": "symbol", "target": "TCS", "impact": 5, "direction": 0.1}]},
    ])
    out = await market.news(mongo, None, None, symbol="TCS", hours=48)
    assert [r["title"] for r in out["items"]] == ["TCS wins deal"]
    assert out["items"][0]["impacts"] == [{"type": "symbol", "target": "TCS", "impact": 7, "direction": 0.6}]


async def test_backdrop_reads_regime_brief_flows(mongo):
    redis = FakeRedis()
    await redis.set("market:regime", json.dumps({"label": "risk_off", "score": -0.6}))
    await redis.set("market:brief", json.dumps({"text": "Crude spikes."}))
    await redis.set("market:flows", json.dumps({"FII": -1200.0, "DII": 900.0, "date": "05-Oct-2026"}))
    out = await market.market_backdrop(mongo, redis, None)
    assert out["regime"]["label"] == "risk_off" and out["brief"] == "Crude spikes." and out["flows"]["FII"] == -1200.0


async def test_tools_return_json_text(mongo):
    await _bars(mongo)
    tool = as_tools(mongo, FakeRedis(), None, ["price_summary"])[0]
    assert json.loads(await tool.ainvoke({"symbol": "TCS"}))["last_close"] == 349.0
