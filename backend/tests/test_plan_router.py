"""GET /plan/today: the latest daily rotation plan the morning pass stored for the caller."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.autopilot.rotation import PLANS
from backend.routers import plan as plan_router
from backend.tests.test_settings_router import _user


def _client(monkeypatch):
    from backend.database import db as database

    mongo = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(database, "db", mongo)
    app = FastAPI()
    app.include_router(plan_router.router)
    app.dependency_overrides[get_current_user] = lambda: _user()
    return TestClient(app), mongo


def test_plan_today_returns_the_latest_plan_of_the_caller_only(monkeypatch):
    import asyncio

    client, mongo = _client(monkeypatch)
    uid = _user().id
    asyncio.run(mongo[PLANS].insert_many([
        {"_id": f"{uid}:2026-11-06", "user_id": uid, "date": "2026-11-06", "exposure": 1.0},
        {"_id": f"{uid}:2026-11-09", "user_id": uid, "date": "2026-11-09", "exposure": 0.0},
        {"_id": "other:2026-11-10", "user_id": "other", "date": "2026-11-10", "exposure": 1.0},
    ]))
    body = client.get("/plan/today").json()
    assert body["plan"] == {"date": "2026-11-09", "exposure": 0.0}


def test_plan_today_without_a_plan(monkeypatch):
    client, _ = _client(monkeypatch)
    assert client.get("/plan/today").json() == {"plan": None}
