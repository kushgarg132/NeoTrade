"""AI summaries (backend/summaries/): each generator builds the right facts, writes once per period,
keeps the last text when the model fails, and the read endpoints are scoped to the user."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.engine.session import IST
from backend.routers import summaries as router
from backend.summaries import activity, core, day, holding
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


# ------------------------------------------------------------------ Ideas: holding notes


def _act(kind, symbol, key="k", title=None):
    return {"id": f"{kind}:{symbol}:{key}", "kind": kind, "symbol": symbol, "title": title or f"{symbol}: news",
            "detail": "Negative news in the last 36 hours.", "rank": 40, "at": NOW, "action": {"type": "stock"}}


@pytest.fixture
def held(db, monkeypatch):
    acts = [_act("bad_news", "DOWN", title="DOWN: misses estimates, cuts guidance"), _act("results_soon", "UP"),
            _act("idea", "OTHER"), _act("overweight", "UP", "limit")]
    build = AsyncMock(return_value=acts)
    monkeypatch.setattr("backend.mine.actions.build", build)
    monkeypatch.setattr("backend.portfolio.digest.verdicts_visible", AsyncMock(return_value=True))
    monkeypatch.setattr("backend.ai.facts.user.portfolio", AsyncMock(return_value={
        "totals": {"value": 100000.0}, "holdings": [
            {"symbol": "DOWN", "quantity": 50, "avg_price": 120.0, "value": 18000.0, "pnl_pct": -7.5, "weight_pct": 18.0},
            {"symbol": "UP", "quantity": 10, "avg_price": 100.0, "value": 1050.0, "pnl_pct": 5.0, "weight_pct": 1.05}]}))
    return acts, build


async def test_a_note_is_written_for_bad_news_and_results_only(db, redis, llm, held):
    llm.reply = "It is a sizeable position; watch the stop."
    await db["holding_theses"].insert_one({"user_id": "alice", "symbol": "DOWN", "why": "turnaround", "stop": 100.0})
    assert await holding.run_user(db, redis, "alice", NOW) == 2
    assert {c["feature"] for c in llm.calls} == {"news"} and {c["tier"] for c in llm.calls} == {"fast"}
    down = next(c for c in llm.calls if "bad_news" in c["prompt"])["prompt"]
    assert "misses estimates" in down and '"weight_pct": 18.0' in down and '"stop": 100.0' in down and "turnaround" in down
    assert await db["ai_summaries"].count_documents({"user_id": "alice", "kind": "holding"}) == 2


async def test_a_note_with_an_invented_figure_is_dropped(db, redis, llm, held):
    llm.reply = "It is 18.0% of your account, down ₹77,777."
    assert await holding.note_for(db, redis, "alice", held[0][0]) is None
    assert await db["ai_summaries"].count_documents({}) == 0


async def test_a_note_is_cached_by_action_id_and_runs_are_throttled(db, redis, llm, held):
    await holding.run_user(db, redis, "alice", NOW)
    assert await holding.run_user(db, redis, "alice", NOW.replace(minute=59)) == 0   # within 30 minutes: not even built
    assert held[1].await_count == 1
    await redis.delete("summary:holding:run:alice")
    assert await holding.run_user(db, redis, "alice", NOW.replace(hour=10)) == 0     # both ids already have a note
    assert len(llm.calls) == 2


async def test_no_pass_outside_the_waking_window(db, redis, llm, held):
    assert await holding.run_user(db, redis, "alice", NOW.replace(hour=3)) == 0
    assert await holding.run_user(db, redis, "alice", NOW.replace(hour=23)) == 0
    assert held[1].await_count == 0 and llm.calls == []


async def test_a_failed_note_is_not_retried_inside_the_back_off_nor_charged_to_the_day(db, redis, llm, held):
    llm.reply = "LLM_DISABLED"
    assert await holding.run_user(db, redis, "alice", NOW) == 0
    assert len(llm.calls) == 2
    await redis.delete("summary:holding:run:alice")
    assert await holding.run_user(db, redis, "alice", NOW.replace(hour=10)) == 0
    assert len(llm.calls) == 2                       # both claims are backing off
    assert int(redis.data["summary:holding:day:alice:2026-10-15"]) == 2


async def test_notes_per_run_and_day_are_capped(db, redis, llm, held, monkeypatch):
    held[0][:] = [_act("bad_news", f"S{i}") for i in range(20)]
    monkeypatch.setattr("backend.ai.facts.user.portfolio", AsyncMock(return_value={
        "totals": {"value": 1.0}, "holdings": [{"symbol": f"S{i}", "value": 1.0} for i in range(20)]}))
    assert await holding.run_user(db, redis, "alice", NOW) == holding.PER_RUN
    for hour in (10, 11):
        await redis.delete("summary:holding:run:alice")
        await holding.run_user(db, redis, "alice", NOW.replace(hour=hour))
    assert len(llm.calls) == holding.PER_DAY


async def test_a_holding_missing_from_the_review_gets_no_call(db, redis, llm, held, monkeypatch):
    monkeypatch.setattr("backend.ai.facts.user.portfolio", AsyncMock(return_value={"error": "none"}))
    assert await holding.run_user(db, redis, "alice", NOW) == 0 and llm.calls == []


async def test_holdings_endpoint_returns_only_the_users_recent_notes(client, db, llm):
    http, holder = client
    at = datetime.now(timezone.utc)
    await db["ai_summaries"].insert_many([
        {"user_id": "alice", "kind": "holding", "key": "bad_news:DOWN:k", "text": "mine", "at": at},
        {"user_id": "alice", "kind": "holding", "key": "old", "text": "old", "at": at.replace(year=2020)},
        {"user_id": "alice", "kind": "day", "key": "d", "text": "not a note", "at": at},
        {"user_id": "bob", "kind": "holding", "key": "bad_news:DOWN:k", "text": "bobs", "at": at}])
    notes = http.get("/api/v1/summaries/holdings").json()["notes"]
    assert list(notes) == ["bad_news:DOWN:k"] and notes["bad_news:DOWN:k"]["text"] == "mine"
    holder["user"] = "carol"
    assert http.get("/api/v1/summaries/holdings").json() == {"notes": {}}
    assert llm.calls == []


# ------------------------------------------------------------------ AI: Activity

CLOSE = datetime(2026, 10, 15, 16, 5, tzinfo=IST)


@pytest.fixture
async def ai_day(db, monkeypatch):
    t = datetime(2026, 10, 15, 10, 0, tzinfo=IST)
    await db["autopilot_log"].insert_many([
        {"user_id": "alice", "at": t, "status": "FILLED", "side": "BUY", "quantity": 10, "symbol": "TCS",
         "source": "picks", "mode": "LONGTERM", "reason": "Pick cleared the fence"},
        {"user_id": "alice", "at": t.replace(hour=11), "status": "REFUSED", "side": "BUY", "quantity": 5, "symbol": "INFY",
         "source": "news", "mode": "INTRADAY", "reason": "risk-off regime blocks news entries"},
        {"user_id": "alice", "at": t - timedelta(days=1), "status": "FILLED", "side": "BUY", "quantity": 1, "symbol": "OLD",
         "source": "picks", "mode": "LONGTERM", "reason": "yesterday"},
        {"user_id": "bob", "at": t, "status": "FILLED", "side": "BUY", "quantity": 99, "symbol": "BOBCO",
         "source": "picks", "mode": "LONGTERM", "reason": "not alice"}])
    monkeypatch.setattr("backend.ai.facts.user.game_plan", AsyncMock(return_value={"plan": {
        "trigger": "pre_open", "skip_day": False, "risk_multiplier": 0.5, "max_positions": 4,
        "rationale": ["Risk-off: half size"], "allow": [{"symbol": "TCS", "strategies": ["orb"]}]}}))
    monkeypatch.setattr("backend.portfolio.digest.pnl_since", AsyncMock(return_value={
        "mine": 0.0, "ai": 1250.5, "ai_charges": 40.0, "mine_charges": 0.0}))


async def test_activity_prompt_has_todays_orders_the_plan_and_the_result_for_this_user(db, redis, llm, ai_day):
    llm.reply = "It filled 1 order and refused 1; the plan halved risk. The day ended at ₹1,250.5."
    doc = await activity.generate(db, redis, "alice", CLOSE)
    assert doc["key"] == "2026-10-15" and doc["text"].startswith("It filled")
    [call] = llm.calls
    assert (call["tier"], call["feature"]) == ("standard", "plan")
    p = call["prompt"]
    assert "Pick cleared the fence" in p and "risk-off regime blocks news entries" in p
    assert "yesterday" not in p and "BOBCO" not in p                      # only today's rows, only this user
    assert "Risk-off: half size" in p and '"risk_multiplier": 0.5' in p and '"orb"' in p
    assert '"ai_net_pnl": 1250.5' in p


async def test_activity_is_once_a_day(db, redis, llm, ai_day):
    assert await activity.generate(db, redis, "alice", CLOSE)
    assert await activity.generate(db, redis, "alice", CLOSE.replace(minute=30)) is None
    assert len(llm.calls) == 1


async def test_activity_with_nothing_to_explain_makes_no_call(db, redis, llm, monkeypatch):
    monkeypatch.setattr("backend.ai.facts.user.game_plan", AsyncMock(return_value={"plan": None}))
    assert await activity.generate(db, redis, "carol", CLOSE) is None and llm.calls == []


async def test_activity_failure_keeps_yesterdays_text(db, redis, llm, ai_day):
    await db["ai_summaries"].insert_one({"user_id": "alice", "kind": "activity", "key": "2026-10-14", "text": "yesterday's",
                                         "at": datetime(2026, 10, 14, 11, tzinfo=timezone.utc)})
    llm.reply = "Error generating response: 500"
    assert await activity.generate(db, redis, "alice", CLOSE) is None
    assert (await core.latest(db, "alice", "activity"))["text"] == "yesterday's"


async def test_activity_run_all_covers_users_with_a_log_row_or_a_plan_today(db, redis, llm, ai_day):
    await db["trade_plans"].insert_one({"user_id": "dave", "date": "2026-10-15"})
    assert await activity.run_all(db, redis, CLOSE) == 3                   # alice, bob, dave
    assert {d["user_id"] async for d in db["ai_summaries"].find({"kind": "activity"})} == {"alice", "bob", "dave"}


async def test_activity_endpoint_is_the_users_latest(client, db, llm):
    http, holder = client
    at = datetime.now(timezone.utc)
    await db["ai_summaries"].insert_many([
        {"user_id": "alice", "kind": "activity", "key": "2026-10-14", "text": "older", "at": at.replace(year=2025)},
        {"user_id": "alice", "kind": "activity", "key": "2026-10-15", "text": "newer", "at": at},
        {"user_id": "bob", "kind": "activity", "key": "2026-10-16", "text": "bobs", "at": at}])
    assert http.get("/api/v1/summaries/activity").json()["summary"]["text"] == "newer"
    holder["user"] = "carol"
    assert http.get("/api/v1/summaries/activity").json() == {"summary": None}
    assert llm.calls == []
