"""Statement headlines: today's Indian market news, newest first, each story
once, nothing older than a day and a half, cached briefly."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    monkeypatch.setattr(news, "_market_cache", {"at": 0.0, "articles": None})
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
    monkeypatch.setattr(news, "_market_cache", {"at": 0.0, "articles": None})
    app = FastAPI()
    app.include_router(news.router, prefix="/api/v1")
    TestClient(app).get("/api/v1/news/market")
    assert news._market_cache["articles"] is None
