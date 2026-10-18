"""Regression tests for the platform/frontend wiki bug batch."""

import asyncio
import time

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend import broadcast
from backend.auth.models import User
from backend.configs.settings import Settings, require_jwt_secret
from backend.ws import routes as ws_routes


def test_empty_or_default_jwt_secret_refused_unless_flagged():
    for secret in ("", "change-me-in-production"):
        with pytest.raises(RuntimeError):
            require_jwt_secret(Settings(JWT_SECRET=secret, ALLOW_INSECURE_JWT_SECRET=False))
        require_jwt_secret(Settings(JWT_SECRET=secret, ALLOW_INSECURE_JWT_SECRET=True))
    require_jwt_secret(Settings(JWT_SECRET="x" * 64, ALLOW_INSECURE_JWT_SECRET=False))


async def test_listen_forever_resubscribes_after_redis_drops(monkeypatch):
    monkeypatch.setattr(broadcast, "RECONNECT_SECONDS", 0)
    calls = []

    async def fake_listen(redis, handlers):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("redis gone")
        if len(calls) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(broadcast, "listen", fake_listen)
    with pytest.raises(asyncio.CancelledError):
        await broadcast.listen_forever(object(), {})
    assert len(calls) == 3


async def test_socket_is_closed_when_its_token_expires():
    closed = []

    class Socket:
        async def close(self, code):
            closed.append(code)

    token = pyjwt.encode({"sub": "u", "exp": int(time.time()) + 1}, "k", algorithm="HS256")
    await asyncio.wait_for(ws_routes._close_at_expiry(Socket(), token), timeout=5)
    assert closed == [ws_routes.CLOSE_UNAUTHORIZED]


async def test_non_jwt_token_does_not_crash_the_expiry_task():
    await ws_routes._close_at_expiry(object(), "good-token")


_USER = User(id="alice", google_sub="s", email="a@x.com", name="A", picture=None,
             created_at=__import__("datetime").datetime(2024, 1, 1, tzinfo=__import__("datetime").timezone.utc))


def _app(router, monkeypatch, module, mongo):
    from backend.auth.dependency import get_current_user
    from backend.database import db as _db
    monkeypatch.setattr(_db, "db", mongo)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _USER
    return TestClient(app)


def test_watchlist_add_rejects_junk_and_first_use_creates_one_row(monkeypatch):
    from backend.routers import watchlist

    mongo = AsyncMongoMockClient()["t"]
    client = _app(watchlist.router, monkeypatch, watchlist, mongo)
    assert client.post("/api/v1/watchlist/add", params={"symbol": "<script>"}).status_code == 422
    assert client.post("/api/v1/watchlist/add", params={"symbol": "M&M"}).json()["symbols"] == ["M&M"]
    client.get("/api/v1/watchlist")
    assert asyncio.run(mongo.watchlist.count_documents({})) == 1


def test_preferences_reject_non_positive_sizes():
    from backend.routers.settings import PreferencesPatch

    for field in ("account_size", "max_exposure", "per_trade_cap"):
        for bad in (-1, 0, float("nan")):
            with pytest.raises(ValueError):
                PreferencesPatch(**{field: bad})
    assert PreferencesPatch(account_size=5000).account_size == 5000


def test_quick_analyze_is_rate_limited_per_user(monkeypatch):
    from backend.routers import agents

    async def deny(*a, **k):
        return False

    monkeypatch.setattr("backend.rate_limit.allow", deny)
    client = _app(agents.router, monkeypatch, agents, AsyncMongoMockClient()["t"])
    assert client.post("/api/v1/quick-analyze/TCS").status_code == 429


async def test_stopping_an_already_stopped_run_is_404(monkeypatch):
    from fastapi import HTTPException

    from backend.routers import trading
    from backend.runs import RunStore
    from backend.routers.trading import StopRequest

    runs = RunStore(AsyncMongoMockClient()["t"])
    await runs.collection.insert_one({"run_id": "r1", "user_id": "alice", "status": "STOPPED"})
    published = []

    async def fake_publish(*a, **k):
        published.append(a)

    monkeypatch.setattr(trading.hub, "publish", fake_publish)
    with pytest.raises(HTTPException) as err:
        await trading.stop_trading(StopRequest(run_id="r1"), user=_USER, runs=runs)
    assert err.value.status_code == 404 and not published


async def test_collection_indexes_are_created_and_unique_ones_enforced():
    from backend.server import ensure_collection_indexes

    mongo = AsyncMongoMockClient()["t"]
    await ensure_collection_indexes(mongo)
    await mongo.watchlist.insert_one({"user_id": "u"})
    with pytest.raises(Exception):
        await mongo.watchlist.insert_one({"user_id": "u"})
