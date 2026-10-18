import json
from unittest.mock import AsyncMock

import pytest

from backend.ai.analyst_verdict import get_cached_verdict, refresh_analyst_verdict


@pytest.mark.asyncio
async def test_get_cached_verdict_miss_returns_none():
    redis = AsyncMock()
    redis.get.return_value = None
    result = await get_cached_verdict("RELIANCE", redis)
    assert result is None
    redis.get.assert_awaited_once_with("analyst_verdict:RELIANCE")


@pytest.mark.asyncio
async def test_get_cached_verdict_hit_returns_dict():
    redis = AsyncMock()
    redis.get.return_value = json.dumps({
        "sentiment_score": 0.5, "impact_score": 7, "label": "bullish", "top_reason": "x",
    })
    result = await get_cached_verdict("RELIANCE", redis)
    assert result["label"] == "bullish"
    assert result["impact_score"] == 7


@pytest.mark.asyncio
async def test_get_cached_verdict_redis_failure_returns_none():
    redis = AsyncMock()
    redis.get.side_effect = OSError("Name or service not known")
    result = await get_cached_verdict("RELIANCE", redis)
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_verdict_rejects_non_dict_value():
    redis = AsyncMock()
    redis.get.return_value = json.dumps([1, 2, 3])  # valid JSON, wrong shape
    result = await get_cached_verdict("RELIANCE", redis)
    assert result is None


class _FakeAnalystAgent:
    async def analyze(self, state):
        return {
            "sentiment_score": 0.5, "impact_score": 7,
            "summary": "Strong quarter driven by margin expansion.\nRisks remain elevated.",
            "events": [{
                "event_type": "earnings", "description": "Beat estimates by 12%",
                "date": "2024-01-01T00:00:00", "symbols": ["RELIANCE"], "impact_rating": 8,
            }],
            "sentiment_analysis": {"score": 0.5, "label": "bullish", "risk_score": 7, "article_count": 3},
        }


@pytest.mark.asyncio
async def test_refresh_analyst_verdict_caches_and_returns(monkeypatch):
    monkeypatch.setattr("backend.ai.analyst.AnalystAgent", _FakeAnalystAgent)
    redis = AsyncMock()

    verdict = await refresh_analyst_verdict("RELIANCE", redis)

    assert verdict == {
        "sentiment_score": 0.5, "impact_score": 7, "label": "bullish",
        "top_reason": "Beat estimates by 12%",
    }
    redis.set.assert_awaited_once()
    args, kwargs = redis.set.await_args
    assert args[0] == "analyst_verdict:RELIANCE"
    assert json.loads(args[1]) == verdict
    assert kwargs["ex"] == 90000


class _NoEventsAgent:
    async def analyze(self, state):
        return {
            "sentiment_score": 0.2, "impact_score": 3,
            "summary": "Modest gains this week.\nNo major catalysts.",
            "events": [], "sentiment_analysis": {"label": "neutral"},
        }


@pytest.mark.asyncio
async def test_refresh_analyst_verdict_falls_back_to_summary_without_events(monkeypatch):
    monkeypatch.setattr("backend.ai.analyst.AnalystAgent", _NoEventsAgent)
    redis = AsyncMock()

    verdict = await refresh_analyst_verdict("TCS", redis)

    assert verdict["top_reason"] == "Modest gains this week."
    assert verdict["label"] == "neutral"
