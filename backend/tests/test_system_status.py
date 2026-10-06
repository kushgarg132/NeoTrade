"""GET /system/status: one admin-only call feeding the handbook's live panels;
each block stands alone, so one broken source never blanks the page."""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db as database
from backend.engine.session import IST
from backend.system import router as system_router
from backend.system import status
from backend.tests.test_datalayer_news import FakeRedis


def _user(role):
    return User(id="alice", google_sub="g", email="a@x.io", name="A", role=role,
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))


@pytest.fixture
def env(monkeypatch):
    mongo, redis = AsyncMongoMockClient()["test_db"], FakeRedis()
    monkeypatch.setattr(database, "db", mongo)
    monkeypatch.setattr(database, "redis", redis)
    monkeypatch.setenv("GIT_SHA", "abc1234")
    status._CACHE.clear()
    return mongo, redis


def _client(role="admin"):
    app = FastAPI()
    app.include_router(system_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    return TestClient(app)


def test_status_shape(env):
    mongo, redis = env
    today = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
    redis.data["job:last:daily_pass"] = {"at": "2026-10-06T10:30:00+00:00", "ok": "1", "note": "{}"}
    redis.data[f"news:deep_calls:{today}"] = "3"
    asyncio.run(mongo["news_items"].insert_one(
        {"title": "x", "status": "SCORED", "published_at": datetime.now(timezone.utc)}))

    body = _client().get("/api/v1/system/status").json()

    assert set(body) == {"as_of", "deploy", "jobs", "news", "data", "ai"}
    assert body["deploy"]["backend_sha"] == "abc1234"
    assert body["jobs"]["daily_pass"]["ok"] is True
    assert body["ai"]["news_calls_today"] == 3
    assert body["news"]["last_24h"]["SCORED"] == 1


def test_status_block_failure_is_isolated(env, monkeypatch):
    async def broken(db, redis):
        raise RuntimeError("mongo down")

    monkeypatch.setitem(status.BLOCKS, "news", broken)
    body = _client().get("/api/v1/system/status").json()
    assert body["news"] == {"error": "RuntimeError: mongo down"}
    assert "error" not in body["deploy"]


def test_status_is_admin_only(env):
    assert _client(role="user").get("/api/v1/system/status").status_code == 403


def test_status_is_cached_30s(env, monkeypatch):
    calls = []
    real = status.build_status

    async def counting(db, redis):
        calls.append(1)
        return await real(db, redis)

    monkeypatch.setattr(status, "build_status", counting)
    client = _client()
    client.get("/api/v1/system/status")
    client.get("/api/v1/system/status")
    assert len(calls) == 1
