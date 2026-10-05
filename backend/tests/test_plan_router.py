from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.engine.session import IST
from backend.plan import store
from backend.plan.validate import TradePlan
from backend.routers import plan as plan_router
from backend.tests.test_datalayer_news import FakeRedis
from backend.tests.test_settings_router import _user


def _client(monkeypatch):
    from backend.database import db as database

    mongo, redis = AsyncMongoMockClient()["test_db"], FakeRedis()
    monkeypatch.setattr(database, "db", mongo)
    monkeypatch.setattr(database, "redis", redis)
    app = FastAPI()
    app.include_router(plan_router.router)
    app.dependency_overrides[get_current_user] = lambda: _user()
    return TestClient(app), mongo, redis


def test_plan_today_returns_plan_versions_and_scorecards(monkeypatch):
    import asyncio

    client, mongo, redis = _client(monkeypatch)
    now = datetime.now(timezone.utc)
    day = now.astimezone(IST).date()
    asyncio.run(store.save(mongo, redis, "alice", day, TradePlan(trigger="pre_open", rationale=["calm"]),
                           now - timedelta(hours=1)))
    asyncio.run(store.save(mongo, redis, "alice", day, TradePlan(trigger="regime_flip", risk_multiplier=0.5), now))
    asyncio.run(mongo["plan_scorecards"].insert_one({"user_id": "alice", "date": day.isoformat(),
                                                     "a": {"net": 10.0, "max_drawdown": 1.0},
                                                     "b": {"net": 5.0, "max_drawdown": 1.0}}))
    body = client.get("/plan/today").json()
    assert body["plan"]["version"] == 2 and body["plan"]["risk_multiplier"] == 0.5
    assert [v["trigger"] for v in body["versions"]] == ["pre_open", "regime_flip"]
    assert body["scorecards"][0]["a"]["net"] == 10.0 and body["weeks_beating"] == 1


def test_plan_today_without_a_plan(monkeypatch):
    client, _, _ = _client(monkeypatch)
    assert client.get("/plan/today").json() == {"plan": None, "versions": [], "scorecards": [], "weeks_beating": 0}
