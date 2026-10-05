import json
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.datalayer import market, news
from backend.tests.test_datalayer_news import FakeRedis

NOW = datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc)  # 11:30 IST, in session


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


def test_calendar_keeps_high_and_medium_events_that_reach_india():
    rows = [
        {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-10-09T08:30:00-04:00", "impact": "High",
         "forecast": "120K", "previous": "98K"},
        {"title": "Bank Holiday", "country": "AUD", "date": "2026-10-04T16:00:00-04:00", "impact": "Holiday"},
        {"title": "NZ data", "country": "NZD", "date": "2026-10-04T16:00:00-04:00", "impact": "High"},
    ]
    [event] = market.parse_calendar(rows)
    assert event["at"] == datetime(2026, 10, 9, 12, 30, tzinfo=timezone.utc) and event["forecast"] == "120K"


def test_regime_rules():
    calm = market.compute_regime(0.1, {"^INDIAVIX": {"value": 12, "percent": 1}}, None, None)
    assert calm["label"] == "neutral" and calm["drivers"] == []

    shock = market.compute_regime(-0.4, {
        "^INDIAVIX": {"value": 26, "percent": 15}, "BZ=F": {"percent": 6}, "INR=X": {"percent": 0.8},
        "ES=F": {"percent": -1.5}}, {"FII": -5200}, None)
    assert shock["label"] == "risk_off" and shock["score"] == -1.0
    assert any("Brent +6.0%" in d for d in shock["drivers"]) and any("FII net" in d for d in shock["drivers"])


def test_brief_cadence():
    assert market._brief_due(None, False, NOW)
    recent = {"at": (NOW - timedelta(minutes=10)).timestamp()}
    assert not market._brief_due(recent, True, NOW)                      # min gap even for big news
    older = {"at": (NOW - timedelta(minutes=20)).timestamp()}
    assert market._brief_due(older, True, NOW) and not market._brief_due(older, False, NOW)
    assert market._brief_due({"at": (NOW - timedelta(minutes=31)).timestamp()}, False, NOW)


def test_brief_off_hours_ignores_big_news_until_the_pre_open():
    night = datetime(2026, 10, 5, 17, 0, tzinfo=timezone.utc)      # 22:30 IST
    two_hours = {"at": (night - timedelta(hours=2)).timestamp()}
    assert not market._brief_due(two_hours, True, night)
    assert market._brief_due({"at": (night - timedelta(hours=6)).timestamp()}, False, night)
    pre_open = datetime(2026, 10, 6, 3, 15, tzinfo=timezone.utc)   # 08:45 IST
    assert market._brief_due({"at": (pre_open - timedelta(minutes=31)).timestamp()}, False, pre_open)


async def test_brief_makes_one_call_and_stores_it(mongo, monkeypatch):
    await mongo[news.COLLECTION].insert_one({
        "_id": "a", "title": "Brent jumps 8%", "source": "CNBC", "status": news.SCORED, "scope": "GLOBAL",
        "published_at": NOW - timedelta(hours=1), "scored_at": NOW - timedelta(minutes=30), "material": True,
        "impacts": [{"type": "market", "target": "INDIA", "direction": -0.5, "impact": 7}]})
    await mongo["econ_calendar"].insert_one({"_id": "x", "at": NOW + timedelta(hours=5), "country": "USD",
                                             "title": "CPI", "impact": "High"})
    prompts = []

    async def write(system, prompt):
        prompts.append(prompt)
        return "### What's moving\nCrude."

    monkeypatch.setattr(market, "_write_brief", write)
    redis = FakeRedis()

    async def mget(keys):
        return [redis.data.get(k) for k in keys]

    redis.mget = mget
    assert await market.brief(mongo, redis, now=NOW)
    assert "Brent jumps 8%" in prompts[0] and "USD CPI" in prompts[0]
    assert json.loads(redis.data["market:brief"])["text"].startswith("### What's moving")
    assert not await market.brief(mongo, redis, now=NOW + timedelta(minutes=5))   # not due again yet
    assert len(prompts) == 1


async def test_chat_search_news_reads_the_store(mongo):
    from backend.chat.tools import read_tools

    now = datetime.now(timezone.utc)
    await mongo[news.COLLECTION].insert_many([
        {"_id": "a", "title": "Fed holds rates", "status": news.SCORED, "scope": "GLOBAL", "published_at": now,
         "symbols": [], "impacts": [{"type": "market", "target": "INDIA", "direction": 0.2, "impact": 5}]},
        {"_id": "b", "title": "TCS wins order", "status": news.SCORED, "scope": "COMPANY", "published_at": now,
         "symbols": ["TCS"], "impacts": [{"type": "symbol", "target": "TCS", "direction": 0.6, "impact": 6}],
         "material": True},
        {"_id": "c", "title": "Fed noise", "status": news.IRRELEVANT, "published_at": now},
    ])
    tool = next(t for t in read_tools(mongo, FakeRedis(), "alice") if t.name == "search_news")
    out = json.loads(await tool.coroutine(query="fed"))
    assert [a["title"] for a in out["articles"]] == ["Fed holds rates"]
    out = json.loads(await tool.coroutine(symbol="tcs", material_only=True))
    assert [a["title"] for a in out["articles"]] == ["TCS wins order"]
