"""analyst.latest: the last read, whether it is stale, and one run per stock."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from backend.ai import analyst
from backend.ai.analyst import AnalystAgent
from backend.tests.test_analyst_agent import REPORT, SCORES, _Redis, _article

# A Tuesday: 11:00 IST is in session, 17:00 IST is after the close.
SESSION = datetime(2026, 10, 27, 5, 30, tzinfo=timezone.utc)
POST = datetime(2026, 10, 27, 11, 30, tzinfo=timezone.utc)


@pytest.fixture
def wired(monkeypatch):
    articles = [_article("SBIN beats"), _article("Top gainers list"), _article("SBIN NPA worry")]
    monkeypatch.setattr(analyst, "fetch_news_logic", AsyncMock(return_value=articles))
    llm = AsyncMock(side_effect=[json.dumps(SCORES), REPORT])
    monkeypatch.setattr(analyst.llm_service, "get_completion", llm)
    redis = _Redis()
    monkeypatch.setattr(analyst, "_redis", lambda: redis)
    monkeypatch.setattr("backend.datalayer.analysis.from_layer", AsyncMock(return_value=None))
    return llm, redis


def _last(redis, at):
    redis.store["analyst:last:SBIN"] = json.dumps({"summary": "s", "at": at.isoformat()})


async def test_store_writes_the_last_read_with_at(wired):
    _, redis = wired
    await AnalystAgent().analyze({"symbol": "SBIN"})
    assert json.loads(redis.store["analyst:last:SBIN"])["at"]
    assert redis.ttls["analyst:last:SBIN"] == analyst.LAST_TTL_SECONDS
    assert redis.ttls["analyst:SBIN"] == analyst.CACHE_TTL_SECONDS
    assert "analyst:lock:SBIN" not in redis.store


@pytest.mark.parametrize("minutes,stale", [(30, False), (61, True)])
async def test_in_session_stale_after_an_hour(wired, minutes, stale):
    _, redis = wired
    _last(redis, SESSION - timedelta(minutes=minutes))
    got = await analyst.latest("SBIN", SESSION)
    assert got["stale"] is stale and got["read"]["summary"] == "s"


async def test_outside_session_stale_only_when_the_4h_key_is_gone(wired):
    _, redis = wired
    _last(redis, POST - timedelta(hours=2))
    redis.store["analyst:SBIN"] = "{}"
    assert (await analyst.latest("SBIN", POST))["stale"] is False
    del redis.store["analyst:SBIN"]
    assert (await analyst.latest("SBIN", POST))["stale"] is True


async def test_no_last_read_is_none(wired):
    assert await analyst.latest("SBIN", SESSION) is None


async def test_latest_without_redis_is_none(monkeypatch):
    monkeypatch.setattr(analyst, "_redis", lambda: None)
    assert await analyst.latest("SBIN") is None


async def test_two_cold_runs_for_an_unfollowed_symbol_call_the_model_once(wired, monkeypatch):
    llm, _ = wired
    real_sleep = asyncio.sleep
    monkeypatch.setattr(analyst.asyncio, "sleep", lambda _s: real_sleep(0))
    await asyncio.gather(AnalystAgent().analyze({"symbol": "SBIN"}), AnalystAgent().analyze({"symbol": "SBIN"}))
    assert llm.await_count == 2  # score + report, once
