"""GET /lab/runs: admin only, newest first, folds left out of the list."""

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.routers import lab as lab_router

NOW = datetime.now(timezone.utc)


def _client(monkeypatch, role="admin"):
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(lab_router.db, "db", db)
    rows = [{"id": "old", "kind": "factor", "name": "mom", "folds": [{"a": 1}], "metrics": {}, "created_at": NOW - timedelta(days=1)},
            {"id": "new", "kind": "study", "name": "gap", "folds": [{"a": 1}], "metrics": {}, "created_at": NOW}]
    asyncio.run(db["lab_runs"].insert_many(rows))
    app = FastAPI()
    app.include_router(lab_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id="alice", google_sub="g", email="a@x.io", name="A", created_at=NOW, role=role)
    return TestClient(app)


def test_admin_lists_newest_first_without_folds_and_filters(monkeypatch):
    client = _client(monkeypatch)
    runs = client.get("/api/v1/lab/runs").json()["runs"]
    assert [r["id"] for r in runs] == ["new", "old"] and all("folds" not in r for r in runs)
    assert [r["id"] for r in client.get("/api/v1/lab/runs?kind=factor").json()["runs"]] == ["old"]


def test_get_run_has_folds_and_unknown_is_404(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/api/v1/lab/runs/new").json()["folds"] == [{"a": 1}]
    assert client.get("/api/v1/lab/runs/nope").status_code == 404


def test_non_admin_is_refused(monkeypatch):
    client = _client(monkeypatch, role="user")
    assert client.get("/api/v1/lab/runs").status_code == 403
    assert client.get("/api/v1/lab/runs/new").status_code == 403
