"""Statement headlines: today's Indian market news, newest first, each story
once, nothing older than a day and a half, cached briefly."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import market_cache
from backend.components.analyst import news
from backend.components.shared.models import NewsArticle


def _article(title, hours_ago):
    return NewsArticle(title=title, url=f"https://x/{hours_ago}/{title}", source="Wire",
                       published_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours_ago))


@pytest.fixture
def searches(monkeypatch):
    calls = []

    async def fake(query, region="US", lang="en-US", limit=10):
        calls.append((query, region, lang))
        return [
            _article("Sensex ends 400 points lower as banks drag - Mint", 2),
            _article("Sensex ends 400 points lower as banks drag - The Economic Times", 3),
            _article("Rupee hits record low against dollar - Reuters", 1),
            _article("Midwest Energy Limited (REMAGNET.BO) stock price", 24 * 60),
        ]

    monkeypatch.setattr(news, "fetch_google_news", fake)
    monkeypatch.setattr(market_cache, "_local", {})
    return calls


@pytest.mark.asyncio
async def test_fresh_headlines_are_newest_first_deduped_and_recent(searches):
    articles = await news.fresh_headlines(news.MARKET_QUERIES)
    assert [a.title for a in articles] == [
        "Rupee hits record low against dollar - Reuters",
        "Sensex ends 400 points lower as banks drag - Mint",
    ]
    assert all(region == "IN" and "when:1d" in q for q, region, _ in searches)


def test_market_route_is_cached_and_never_searches_ticker_codes(searches):
    app = FastAPI()
    app.include_router(news.router, prefix="/api/v1")
    client = TestClient(app)

    first = client.get("/api/v1/news/market").json()["articles"]
    second = client.get("/api/v1/news/market").json()["articles"]

    assert first == second and len(first) == 2
    assert len(searches) == len(news.MARKET_QUERIES)  # second call served from cache
    assert not any("^" in q for q, _, _ in searches)


def test_an_empty_answer_is_not_cached(monkeypatch):
    async def nothing(query, region="US", lang="en-US", limit=10):
        return []
    monkeypatch.setattr(news, "fetch_google_news", nothing)
    monkeypatch.setattr(market_cache, "_local", {})
    app = FastAPI()
    app.include_router(news.router, prefix="/api/v1")
    TestClient(app).get("/api/v1/news/market")
    assert "news" not in market_cache._local


def test_news_feed_filters_to_the_users_names(monkeypatch):
    import asyncio
    from mongomock_motor import AsyncMongoMockClient
    from backend.auth.dependency import get_current_user
    from backend.auth.models import User
    from backend.database import db as database

    mongo = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(database, "db", mongo)
    now = datetime.now(timezone.utc)

    def item(_id, minutes, **extra):
        return {"_id": _id, "title": _id, "status": "SCORED", "scope": "COMPANY", "symbols": [], "impacts": [],
                "published_at": now - timedelta(minutes=minutes), **extra}

    asyncio.run(mongo["news_items"].insert_many([
        item("tcs", 1, symbols=["TCS"]), item("infy", 2, impacts=[{"type": "symbol", "target": "INFY"}]),
        item("rbi", 3, scope="MACRO"), item("junk", 4, status="IRRELEVANT"),
        item("record-date", 5, source="NSE filing", symbols=["WIPRO"]),
        item("order-win", 6, source="NSE filing", symbols=["HDFCBANK"], impacts=[{"type": "symbol", "target": "HDFCBANK"}]),
    ]))
    asyncio.run(mongo["portfolio_snapshots"].insert_one(
        {"user_id": "alice", "at": now, "holdings": [{"symbol": "HDFCBANK"}, {"symbol": "WIPRO"}]}))
    asyncio.run(mongo["paper_positions"].insert_one({"user_id": "alice", "symbol": "TCS.NS", "quantity": 1}))
    asyncio.run(mongo["watchlist"].insert_one({"user_id": "alice", "symbols": ["INFY"]}))

    app = FastAPI()
    app.include_router(news.router)
    app.dependency_overrides[get_current_user] = lambda: User(id="alice", google_sub="g", email="a@x.io", name="A",
                                                             created_at=now)
    client = TestClient(app)
    ids = lambda **params: [i["id"] for i in client.get("/news/feed", params=params).json()["items"]]
    # A filing the scorer found moves nothing is left out; one that moves a name stays.
    assert ids() == ["tcs", "infy", "rbi", "order-win"]
    # Mine: paper positions, the watchlist and the broker holdings.
    assert ids(mine=True) == ["tcs", "infy", "order-win"]
    assert ids(scope="MACRO") == ["rbi"]
    assert ids(limit=1) == ["tcs"]


def _symbols_client(monkeypatch, items, sentiments):
    import asyncio

    from mongomock_motor import AsyncMongoMockClient

    from backend.auth.dependency import get_current_user
    from backend.auth.models import User
    from backend.database import db as database
    from backend.tests.test_datalayer_news import FakeRedis

    mongo, redis = AsyncMongoMockClient()["test_db"], FakeRedis()
    monkeypatch.setattr(database, "db", mongo)
    monkeypatch.setattr(database, "redis", redis)
    for symbol, value in sentiments.items():
        redis.data[f"sentiment:{symbol}"] = str(value)
    if items:
        asyncio.run(mongo["news_items"].insert_many(items))
    app = FastAPI()
    app.include_router(news.router)
    app.dependency_overrides[get_current_user] = lambda: User(id="alice", google_sub="g", email="a@x.io", name="A",
                                                             created_at=datetime.now(timezone.utc))
    return TestClient(app)


def test_symbol_news_summarises_sentiment_and_latest_headline(monkeypatch):
    now = datetime.now(timezone.utc)

    def item(_id, hours, target, impact, direction, material=False):
        return {"_id": _id, "title": f"title {_id}", "url": f"https://x/{_id}", "status": "SCORED",
                "material": material, "published_at": now - timedelta(hours=hours),
                "impacts": [{"type": "symbol", "target": target, "impact": impact, "direction": direction}]}
    client = _symbols_client(monkeypatch, [item("old", 5, "TCS", 9, 0.8), item("new", 1, "TCS", 7, -0.6, True),
                                           item("stale", 100, "INFY", 9, 0.9)], {"TCS": -0.3, "WIPRO": 0.1})
    body = client.get("/news/symbols", params={"symbols": "tcs.NS,INFY,WIPRO"}).json()["symbols"]
    assert body["TCS"]["headline"] == "title new" and body["TCS"]["direction"] == -0.6
    assert body["TCS"]["material"] is True and body["TCS"]["sentiment"] == -0.3
    assert body["WIPRO"] == {"sentiment": 0.1, "headline": None, "direction": None, "impact": None,
                             "material": False, "published_at": None, "url": None}
    assert "INFY" not in body  # its only news is older than 72h and it has no sentiment


def test_symbol_news_omits_quiet_names_and_caps_the_list(monkeypatch):
    client = _symbols_client(monkeypatch, [], {})
    many = ",".join(f"S{i}" for i in range(150))
    response = client.get("/news/symbols", params={"symbols": many})
    assert response.status_code == 200 and response.json() == {"symbols": {}}
    assert client.get("/news/symbols", params={"symbols": ""}).json() == {"symbols": {}}


def test_symbol_news_prefers_material_bad_news_and_judges_materiality_per_symbol(monkeypatch):
    now = datetime.now(timezone.utc)

    def item(_id, hours, impacts, material=True):
        return {"_id": _id, "title": f"title {_id}", "url": None, "status": "SCORED", "material": material,
                "published_at": now - timedelta(hours=hours), "impacts": impacts}
    client = _symbols_client(monkeypatch, [
        item("big", 5, [{"type": "symbol", "target": "TCS", "impact": 8, "direction": -0.8}]),
        item("small", 1, [{"type": "symbol", "target": "TCS", "impact": 2, "direction": 0.1}], material=False),
        # material for the sector, only 2/10 for INFY itself
        item("sector", 1, [{"type": "sector", "target": "IT", "impact": 9, "direction": -0.9},
                           {"type": "symbol", "target": "INFY", "impact": 2, "direction": -0.2}]),
    ], {})
    body = client.get("/news/symbols", params={"symbols": "TCS,INFY"}).json()["symbols"]
    assert body["TCS"]["headline"] == "title big" and body["TCS"]["material"] is True
    assert body["INFY"]["material"] is False


def test_symbol_news_reads_sentiment_in_one_round_trip(monkeypatch):
    client = _symbols_client(monkeypatch, [], {"TCS": 0.3, "INFY": -0.2})
    from backend.database import db as database

    gets = []
    original = database.redis.get

    async def counting_get(key):
        gets.append(key)
        return await original(key)
    database.redis.get = counting_get
    body = client.get("/news/symbols", params={"symbols": "TCS,INFY"}).json()["symbols"]
    assert body["TCS"]["sentiment"] == 0.3 and body["INFY"]["sentiment"] == -0.2 and gets == []
