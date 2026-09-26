"""AnalystAgent: two LLM calls per stock, sentiment from relevant articles
only (impact- and recency-weighted), strict JSON with one retry, and a shared
per-symbol cache that also feeds the engine's sentiment cache."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from backend.components.analyst import agent as agent_module
from backend.components.analyst.agent import AnalystAgent, _weighted_sentiment, _ArticleScore
from backend.components.shared.models import NewsArticle

NOW = datetime.now(timezone.utc)


def _article(title, age_days=0):
    return NewsArticle(title=title, url="https://x", source="t", published_at=NOW - timedelta(days=age_days),
                       content=f"{title} body")


SCORES = {
    "articles": [
        {"index": 0, "is_relevant": True, "sentiment": "POSITIVE", "score": 0.8, "impact": 8},
        {"index": 1, "is_relevant": False, "sentiment": "NEUTRAL", "score": 0.0, "impact": 1},
        {"index": 2, "is_relevant": True, "sentiment": "NEGATIVE", "score": -0.4, "impact": 2},
    ],
    "events": [{"event_type": "earnings", "description": "Q1 beat.", "impact_rating": 8}],
}
REPORT = "### Market Sentiment\nBullish.\n===THESIS===\nA strong quarter."


class _Redis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


@pytest.fixture
def wired(monkeypatch):
    articles = [_article("SBIN beats"), _article("Top gainers list"), _article("SBIN NPA worry")]
    monkeypatch.setattr(agent_module, "fetch_news_logic", AsyncMock(return_value=articles))
    llm = AsyncMock(side_effect=[f"```json\n{json.dumps(SCORES)}\n```", REPORT])
    monkeypatch.setattr(agent_module.llm_service, "get_completion", llm)
    redis = _Redis()
    monkeypatch.setattr(agent_module, "_redis", lambda: redis)
    return llm, redis


async def test_two_calls_relevant_only_weighted_sentiment_and_split_report(wired):
    llm, _ = wired
    out = await AnalystAgent().analyze({"symbol": "SBIN"})

    assert llm.await_count == 2
    # (64 * 0.8 + 4 * -0.4) / (64 + 4); the irrelevant article is not a 0 in the average.
    assert out["sentiment_score"] == pytest.approx(49.6 / 68)
    assert out["sentiment_analysis"]["relevant_count"] == 2
    assert out["sentiment_analysis"]["article_count"] == 3
    assert out["sentiment_analysis"]["label"] == "bullish"
    assert out["impact_score"] == 8
    assert out["events"][0]["description"] == "Q1 beat."
    assert out["summary"] == "### Market Sentiment\nBullish."
    assert out["thesis"] == "A strong quarter."
    assert out["news_articles"][1]["sentiment"] is None


async def test_result_is_cached_and_feeds_the_engine_sentiment_cache(wired):
    llm, redis = wired
    first = await AnalystAgent().analyze({"symbol": "SBIN"})
    second = await AnalystAgent().analyze({"symbol": "SBIN"})

    assert llm.await_count == 2  # the second analysis made no calls
    assert second == first
    assert float(redis.store["sentiment:SBIN"]) == pytest.approx(49.6 / 68)


async def test_invalid_json_is_retried_once(monkeypatch, wired):
    llm, _ = wired
    llm.side_effect = ["Sure! Here you go: not json", json.dumps(SCORES), REPORT]
    out = await AnalystAgent().analyze({"symbol": "SBIN"})
    assert llm.await_count == 3
    assert out["sentiment_analysis"]["relevant_count"] == 2


async def test_unusable_scores_leave_sentiment_neutral_but_still_write_the_note(monkeypatch, wired):
    llm, _ = wired
    llm.side_effect = ["nope", '{"articles": [{"index": 0, "is_relevant": true, "score": 7}]}', REPORT]
    out = await AnalystAgent().analyze({"symbol": "SBIN"})
    assert out["sentiment_score"] == 0.0
    assert out["sentiment_analysis"]["relevant_count"] == 0
    assert out["thesis"] == "A strong quarter."


async def test_no_news_makes_no_llm_call_and_is_not_cached(monkeypatch, wired):
    llm, redis = wired
    monkeypatch.setattr(agent_module, "fetch_news_logic", AsyncMock(return_value=[]))
    out = await AnalystAgent().analyze({"symbol": "SBIN"})
    assert llm.await_count == 0
    assert out["sentiment_score"] == 0.0
    assert redis.store == {}


def test_older_news_counts_for_less():
    fresh = (_article("new"), _ArticleScore(index=0, is_relevant=True, score=1.0, impact=5))
    old = (_article("old", age_days=30), _ArticleScore(index=1, is_relevant=True, score=-1.0, impact=5))
    # Weights 25 and 12.5 (one 30-day half-life): (25 - 12.5) / 37.5
    assert _weighted_sentiment([fresh, old], NOW) == pytest.approx(1 / 3, abs=1e-3)


def test_a_big_older_earnings_miss_outweighs_a_fresh_minor_puff_piece():
    """The real Tata Elxsi case (2026-09-26) that a 3-day half-life got
    wrong: it scored +0.60 while the written report said Bearish."""
    scored = [
        (_article("Fundamentals behind gain", age_days=11), _ArticleScore(index=0, is_relevant=True, score=0.6, impact=4)),
        (_article("Shares slide 6% after weak Q1", age_days=73), _ArticleScore(index=1, is_relevant=True, score=-0.7, impact=7)),
        (_article("Five-year low after PAT -23%", age_days=73), _ArticleScore(index=2, is_relevant=True, score=-0.8, impact=8)),
        (_article("Ex-dividend in three days", age_days=112), _ArticleScore(index=3, is_relevant=True, score=0.0, impact=2)),
    ]
    assert _weighted_sentiment(scored, NOW) < -0.15  # bearish, like the report
