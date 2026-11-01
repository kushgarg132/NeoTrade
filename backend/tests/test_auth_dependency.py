import asyncio

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user, get_optional_user, get_user_store
from backend.auth.jwt import create_session_jwt
from backend.auth.store import UserStore


def _make_app():
    app = FastAPI()

    @app.get("/protected")
    async def protected(user=Depends(get_current_user)):
        return {"user_id": user.id}

    return app


def test_missing_authorization_header_returns_401_or_403():
    client = TestClient(_make_app())
    resp = client.get("/protected")
    assert resp.status_code in (401, 403)


def test_valid_token_for_known_user_succeeds():
    store = UserStore(AsyncMongoMockClient()["test_db"])
    user = asyncio.run(store.upsert_from_google(
        google_sub="g1", email="a@example.com", name="Alice", picture=None,
    ))
    token = create_session_jwt(user.id)

    app = _make_app()

    async def _override():
        return store

    app.dependency_overrides[get_user_store] = _override
    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == user.id


def test_token_for_unknown_user_returns_401():
    store = UserStore(AsyncMongoMockClient()["test_db"])
    token = create_session_jwt("no-such-user-id")

    app = _make_app()

    async def _override():
        return store

    app.dependency_overrides[get_user_store] = _override
    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_tampered_token_returns_401():
    # get_current_user's own `user_store` Depends() is resolved before its
    # body runs (FastAPI resolves all declared dependencies upfront, not
    # lazily based on what the body ends up doing) -- so even a request
    # that will fail on the tampered token still needs a working
    # get_user_store override, same as the other tests here, or
    # UserStore(db.db) crashes on the real (unconnected) global db.db.
    store = UserStore(AsyncMongoMockClient()["test_db"])
    token = create_session_jwt("some-user-id")
    mid = len(token) // 2
    flipped_char = "A" if token[mid] != "A" else "B"
    tampered = token[:mid] + flipped_char + token[mid + 1:]

    app = _make_app()

    async def _override():
        return store

    app.dependency_overrides[get_user_store] = _override
    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {tampered}"})
    assert resp.status_code == 401


def _open_app(store):
    app = FastAPI()

    @app.get("/open")
    async def open_(user=Depends(get_optional_user)):
        return {"user_id": user.id if user else None}

    async def _override():
        return store

    app.dependency_overrides[get_user_store] = _override
    return TestClient(app)


def test_optional_no_header_is_guest():
    resp = _open_app(UserStore(AsyncMongoMockClient()["test_db"])).get("/open")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": None}


def test_optional_valid_token_returns_user():
    store = UserStore(AsyncMongoMockClient()["test_db"])
    user = asyncio.run(store.upsert_from_google(
        google_sub="g1", email="a@example.com", name="Alice", picture=None,
    ))
    resp = _open_app(store).get(
        "/open", headers={"Authorization": f"Bearer {create_session_jwt(user.id)}"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == user.id


def test_invalid_token_is_401_not_guest():
    resp = _open_app(UserStore(AsyncMongoMockClient()["test_db"])).get(
        "/open", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


def test_optional_token_for_deleted_user_is_401():
    resp = _open_app(UserStore(AsyncMongoMockClient()["test_db"])).get(
        "/open", headers={"Authorization": f"Bearer {create_session_jwt('gone')}"})
    assert resp.status_code == 401
