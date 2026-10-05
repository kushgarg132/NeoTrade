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
    ]))
    asyncio.run(mongo["paper_positions"].insert_one({"user_id": "alice", "symbol": "TCS.NS", "quantity": 1}))
    asyncio.run(mongo["watchlist"].insert_one({"user_id": "alice", "symbols": ["INFY"]}))

    app = FastAPI()
    app.include_router(news.router)
    app.dependency_overrides[get_current_user] = lambda: User(id="alice", google_sub="g", email="a@x.io", name="A",
                                                             created_at=now)
    client = TestClient(app)
    ids = lambda **params: [i["id"] for i in client.get("/news/feed", params=params).json()["items"]]
    assert ids() == ["tcs", "infy", "rbi"]
    assert ids(mine=True) == ["tcs", "infy"]
    assert ids(scope="MACRO") == ["rbi"]
    assert ids(limit=1) == ["tcs"]
