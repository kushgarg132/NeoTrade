"""Built strategies over the API, the chat and the Jobs panel."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.builder import draft
from backend.chat.tools import read_tools
from backend.database import db as database
from backend.learning.library import catalog
from backend.routers import settings as settings_router
from backend.system import router as system_router
from backend.system import status
from backend.tests.test_datalayer_news import FakeRedis
from backend.tests.test_settings_router import _user
from backend.tests.test_builder_store import SPEC


def _doc(slug, status_, verdict="ok"):
    return {"slug": slug, "status": status_, "description": f"{slug} desc", "thesis": f"{slug} thesis",
            "verdict": verdict, "metrics": {"year": {"pf": 1.4}}, "spec": SPEC,
            "drafted_at": datetime(2026, 10, 2, tzinfo=timezone.utc)}


@pytest.fixture
def env(monkeypatch):
    mongo, redis = AsyncMongoMockClient()["test_db"], FakeRedis()
    monkeypatch.setattr(database, "db", mongo)
    monkeypatch.setattr(database, "redis", redis)
    status._CACHE.clear()
    return mongo, redis


def _client(role="user"):
    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/v1")
    app.include_router(system_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _user(role=role)
    return TestClient(app)


async def test_built_endpoint_groups_by_status(env):
    mongo, _ = env
    for slug, st in (("a", "active"), ("b", "rejected"), ("c", "retired"), ("d", "testing")):
        await mongo["built_strategies"].insert_one(_doc(slug, st))
    body = _client().get("/api/v1/strategies/built").json()
    assert {k: [r["slug"] for r in v] for k, v in body.items()} == {
        "active": ["a"], "rejected": ["b"], "retired": ["c"], "testing": ["d"]}
    assert set(body["active"][0]) == {"slug", "description", "thesis", "verdict", "metrics", "drafted_at", "mine"}


def test_run_is_admin_only(env):
    assert _client("user").post("/api/v1/system/builder/run").status_code == 403


def test_run_while_locked_is_409(env):
    _, redis = env
    redis.data[draft.LOCK] = "x"
    with patch.object(draft, "spawn", AsyncMock()) as spawn:
        r = _client("admin").post("/api/v1/system/builder/run")
    assert r.status_code == 409 and r.json()["detail"] == "The builder is already running."
    spawn.assert_not_awaited()


def test_run_spawns_the_process(env):
    with patch.object(draft, "spawn", AsyncMock()) as spawn:
        r = _client("admin").post("/api/v1/system/builder/run")
    assert r.json() == {"started": True}
    spawn.assert_awaited_once()


async def test_chat_tool_returns_the_built_strategies(env):
    mongo, _ = env
    await mongo["built_strategies"].insert_one(_doc("a", "active"))
    tools = {t.name: t for t in read_tools(mongo, None, "alice")}
    out = await tools["get_built_strategies"].ainvoke({})
    assert '"slug": "a"' in out and '"status": "active"' in out


async def test_catalog_row_for_a_built_strategy_carries_the_verdict(env):
    mongo, _ = env
    await mongo["built_strategies"].insert_one(_doc("a", "active", verdict="holdout passed"))
    row = next(c for c in await catalog(mongo, "alice", []) if c["name"] == "built:a")
    assert row["built"] == {"description": "a desc", "thesis": "a thesis",
                            "metrics": {"year": {"pf": 1.4}}, "verdict": "holdout passed"}
    assert "built" not in next(c for c in await catalog(mongo, "alice", []) if not c["name"].startswith("built:"))


async def test_jobs_block_reports_the_builder_run(env):
    _, redis = env
    redis.data["job:last:strategy_builder"] = {"at": "2026-10-02T20:00:00+00:00", "ok": "1", "note": "done"}
    assert (await status._jobs(None, redis))["builder"]["ok"] is True
