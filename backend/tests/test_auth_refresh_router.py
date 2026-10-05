"""/auth/* -- refresh-token issuance, rotation, and logout.

The access token is short-lived on purpose; these routes are what let a
returning browser silently mint a new one without the user ever seeing the
Google button again. The cookie itself is the thing under test as much as
the JSON body: it must be httpOnly (no JS access), and it must never put the
raw token anywhere a response body or log line could leak it.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_user_store
from backend.auth.models import User
from backend.auth.refresh_store import RefreshTokenStore
from backend.configs.settings import settings
from backend.routers import auth as auth_router

_USER = User(
    id="u1", google_sub="sub-1", email="u1@example.com", name="U One",
    picture=None, created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
)


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


@pytest.fixture
def refresh_store(mongo):
    return RefreshTokenStore(mongo)


class _FakeUserStore:
    async def upsert_from_google(self, **kwargs):
        return _USER

    async def get_by_id(self, user_id):
        return _USER if user_id == _USER.id else None


@pytest.fixture
def client(refresh_store):
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1")
    app.dependency_overrides[get_user_store] = lambda: _FakeUserStore()
    app.dependency_overrides[auth_router.get_refresh_store] = lambda: refresh_store
    return TestClient(app)


def _login(client):
    with patch("backend.routers.auth.verify_google_token", new=AsyncMock(return_value=_google_info())):
        return client.post("/api/v1/auth/google", json={"id_token": "whatever"})


def _google_info():
    from backend.auth.google import GoogleUserInfo

    return GoogleUserInfo(sub="sub-1", email="u1@example.com", name="U One", picture=None)


def test_login_sets_an_httponly_refresh_cookie(client):
    resp = _login(client)

    assert resp.status_code == 200
    cookie_header = resp.headers.get("set-cookie", "")
    assert settings.REFRESH_COOKIE_NAME in cookie_header
    assert "HttpOnly" in cookie_header
    assert "samesite=none" in cookie_header.lower()


def test_login_never_puts_the_refresh_token_in_the_response_body(client):
    resp = _login(client)

    cookie_value = resp.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert cookie_value
    assert cookie_value not in resp.text


def test_refresh_with_a_valid_cookie_returns_a_new_access_token(client):
    login = _login(client)
    client.cookies.set(settings.REFRESH_COOKIE_NAME, login.cookies.get(settings.REFRESH_COOKIE_NAME))

    resp = client.post("/api/v1/auth/refresh")

    assert resp.status_code == 200
    assert "token" in resp.json()


def test_refresh_rotates_the_cookie(client):
    login = _login(client)
    first_cookie = login.cookies.get(settings.REFRESH_COOKIE_NAME)
    client.cookies.set(settings.REFRESH_COOKIE_NAME, first_cookie)

    resp = client.post("/api/v1/auth/refresh")

    new_cookie = resp.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert new_cookie and new_cookie != first_cookie


def test_refresh_with_no_cookie_is_unauthorized(client):
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


def test_refresh_with_a_garbage_cookie_is_unauthorized(client):
    client.cookies.set(settings.REFRESH_COOKIE_NAME, "not-a-real-token")
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


def test_reusing_a_rotated_away_cookie_is_refused(client, refresh_store):
    import asyncio
    from datetime import datetime, timedelta, timezone

    login = _login(client)
    client.cookies.set(settings.REFRESH_COOKIE_NAME, login.cookies.get(settings.REFRESH_COOKIE_NAME))
    client.post("/api/v1/auth/refresh")  # rotates it away
    # ...a minute ago: past the grace window two tabs get for a shared cookie.
    asyncio.run(refresh_store.collection.update_many(
        {"rotated": True}, {"$set": {"revoked_at": datetime.now(timezone.utc) - timedelta(minutes=1)}}))

    # The browser replays the original (now-dead) cookie.
    client.cookies.set(settings.REFRESH_COOKIE_NAME, login.cookies.get(settings.REFRESH_COOKIE_NAME))
    resp = client.post("/api/v1/auth/refresh")

    assert resp.status_code == 401


def test_logout_clears_the_cookie_and_revokes_it(client, refresh_store):
    import asyncio

    login = _login(client)
    raw = login.cookies.get(settings.REFRESH_COOKIE_NAME)
    client.cookies.set(settings.REFRESH_COOKIE_NAME, raw)

    resp = client.post("/api/v1/auth/logout")

    assert resp.status_code == 200
    assert asyncio.run(refresh_store.rotate(raw)) is None


def test_logout_without_a_cookie_still_succeeds(client):
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
