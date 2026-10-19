"""AI summaries (backend/summaries/): each generator builds the right facts, writes once per period,
keeps the last text when the model fails, and the read endpoints are scoped to the user."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.engine.session import IST
from backend.routers import summaries as router
from backend.summaries import core, day
from backend.tests.test_datalayer_news import FakeRedis

NOW = datetime(2026, 10, 15, 8, 50, tzinfo=IST)


class FakeLLM:
    """Stands in for llm_service.get_completion; records every prompt."""

    def __init__(self, reply="ok"):
        self.reply, self.calls = reply, []

    async def __call__(self, prompt, system_prompt, tier=None, feature=None):
        self.calls.append({"prompt": prompt, "system": system_prompt, "tier": tier, "feature": feature})
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(core.llm_service, "get_completion", fake)
    return fake


@pytest.fixture
def db():
    return AsyncMongoMockClient()["t"]


@pytest.fixture
def redis():
    return FakeRedis()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(router.db, "db", db)
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")
    holder = {"user": "alice"}
    app.dependency_overrides[get_current_user] = lambda: User(
        id=holder["user"], google_sub="g", email="a@x.io", name="A", created_at=NOW)
    return TestClient(app), holder


# ------------------------------------------------------------------ Home: Your day

DIGEST = "☀️ <b>Before the open</b>\nYour account: ₹2,950, yesterday −₹50 (-1.7%)\nNeeds you (1):\n• DOWN: HOLD → SELL"


@pytest.fixture
def day_facts(monkeypatch):
    monkeypatch.setattr("backend.portfolio.digest._actions", AsyncMock(return_value=[{"title": "DOWN: HOLD → SELL"}]))
    monkeypatch.setattr("backend.ai.facts.market.market_backdrop", AsyncMock(return_value={
        "brief": "Crude is up 3.1%.", "regime": {"label": "risk_off", "score": -0.6, "drivers": ["Brent +3.1%"]},
        "markets": [{"name": "Nifty 50", "value": 24800.0, "percent": -0.4, "extra": 1}]}))


async def test_day_prompt_carries_only_the_digest_needs_and_market(db, redis, llm, day_facts):
    llm.reply = "You hold ₹2,950, down ₹50 yesterday.\nOne item needs you: DOWN.\nThe regime is risk_off."
    doc = await day.generate(db, redis, "alice", "pre", NOW, DIGEST)
    assert doc["key"] == "2026-10-15:pre" and doc["text"].count("\n") == 2
    [call] = llm.calls
    assert (call["tier"], call["feature"]) == ("fast", "portfolio")
    assert "Your account: ₹2,950" in call["prompt"] and "<b>" not in call["prompt"]
    assert "DOWN: HOLD → SELL" in call["prompt"] and "risk_off" in call["prompt"] and "Nifty 50" in call["prompt"]
    assert "before the market opens" in call["prompt"]


async def test_day_is_written_once_per_phase_and_date(db, redis, llm, day_facts):
    llm.reply = "Line one.\nLine two.\nLine three.\nLine four."
    assert (await day.generate(db, redis, "alice", "pre", NOW, DIGEST))["text"] == "Line one.\nLine two.\nLine three."
    assert await day.generate(db, redis, "alice", "pre", NOW.replace(minute=55), DIGEST) is None
    assert len(llm.calls) == 1
    assert await day.generate(db, redis, "alice", "post", NOW.replace(hour=16, minute=5), DIGEST)
    assert len(llm.calls) == 2


@pytest.mark.parametrize("reply", ["LLM_DISABLED", "Error generating response: boom", "", RuntimeError("down")])
async def test_a_failed_call_keeps_the_last_text_and_backs_off(db, redis, llm, day_facts, reply):
    llm.reply = "Fine.\nFine.\nFine."
    await day.generate(db, redis, "alice", "pre", NOW, DIGEST)
    llm.reply = reply
    assert await day.generate(db, redis, "alice", "post", NOW.replace(hour=16, minute=5), DIGEST) is None
    assert await day.generate(db, redis, "alice", "post", NOW.replace(hour=16, minute=6), DIGEST) is None
    assert len(llm.calls) == 2  # the second post attempt waited out the back-off
    assert (await core.get(db, "alice", "day", "2026-10-15:pre"))["text"].startswith("Fine")


async def test_a_daily_limit_is_skipped_silently(db, redis, llm, day_facts):
    from backend.llm import DailyLimitReached

    llm.reply = DailyLimitReached("alice")
    assert await day.generate(db, redis, "alice", "pre", NOW, DIGEST) is None


async def test_an_invented_figure_is_dropped(db, redis, llm, day_facts):
    llm.reply = "You hold ₹2,950.\nYou are up ₹9,999 this month."
    assert (await day.generate(db, redis, "alice", "pre", NOW, DIGEST))["text"] == "You hold ₹2,950."


async def test_day_endpoint_is_the_users_own_latest_and_never_calls_the_model(client, db, llm):
    http, holder = client
    today = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
    at = datetime.now(timezone.utc)
    for user, phase, text in (("alice", "pre", "morning"), ("alice", "post", "evening"), ("bob", "post", "bobs")):
        await db["ai_summaries"].insert_one({"user_id": user, "kind": "day", "key": f"{today}:{phase}", "text": text, "at": at})
    body = http.get("/api/v1/summaries/day").json()["summary"]
    assert body["text"] == "evening" and body["phase"] == "post"
    holder["user"] = "carol"
    assert http.get("/api/v1/summaries/day").json() == {"summary": None}
    assert llm.calls == []
