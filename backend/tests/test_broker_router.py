"""/broker/{broker}/* -- the Settings card's view of a broker session, for
any broker in backend.brokers.registry.BROKERS.

Adapter internals are already covered per-broker (test_kite_adapter.py,
test_upstox_adapter.py, test_angel_one_adapter.py); what matters here is
that the routes report a state the UI can act on, dispatch to the right
adapter via the credential store, and never leak a broker token to the
client.
"""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.broker_credentials import get_credential_store
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.brokers.protocol import BrokerSessionState
from backend.routers import broker

_USER = User(
    id="alice", google_sub="sub-1", email="alice@example.com", name="Alice",
    picture=None, created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
)


class _FakeAdapter:
    def __init__(self, state=BrokerSessionState.NEEDS_LOGIN, fail_connect=False, login_url="https://example.com/login"):
        self._state = state
        self.fail_connect = fail_connect
        self._login_url = login_url
        self.cleared = False
        self.connected_with = None

    async def state(self):
        return self._state

    async def login_url(self):
        if self._state == BrokerSessionState.UNCONFIGURED:
            raise RuntimeError("API key is not configured")
        return self._login_url

    async def connect(self, **fields):
        if self.fail_connect:
            raise Exception("broker rejected the attempt")
        self.connected_with = fields
        self._state = BrokerSessionState.ACTIVE
        return "access-token-value"

    async def disconnect(self):
        self.cleared = True
        self._state = BrokerSessionState.NEEDS_LOGIN

    async def instruments(self, exchanges=("NSE", "BSE")):
        return []


def _client(adapter, monkeypatch):
    async def fake_get_broker_adapter(broker_name, user_id, credentials, redis):
        return adapter

    monkeypatch.setattr(broker, "get_broker_adapter", fake_get_broker_adapter)

    app = FastAPI()
    app.include_router(broker.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_credential_store] = lambda: None
    return TestClient(app)


def test_list_returns_the_known_brokers(monkeypatch):
    resp = _client(_FakeAdapter(), monkeypatch).get("/api/v1/broker/list")
    assert resp.status_code == 200
    assert set(resp.json()["brokers"]) == {"kite", "upstox", "angel_one"}


def test_unknown_broker_is_a_404():
    app = FastAPI()
    app.include_router(broker.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_credential_store] = lambda: None

    resp = TestClient(app).get("/api/v1/broker/robinhood/status")
    assert resp.status_code == 404


def test_status_tells_the_ui_what_to_do_next(monkeypatch):
    resp = _client(_FakeAdapter(), monkeypatch).get("/api/v1/broker/kite/status")

    assert resp.status_code == 200
    assert resp.json() == {"state": "NEEDS_LOGIN", "connected": False, "action": "Connect your account"}


def test_an_active_session_needs_no_action(monkeypatch):
    resp = _client(_FakeAdapter(BrokerSessionState.ACTIVE), monkeypatch).get("/api/v1/broker/kite/status")

    assert resp.json()["connected"] is True
    assert resp.json()["action"] is None


def test_login_url_is_returned_for_the_human_to_visit(monkeypatch):
    resp = _client(_FakeAdapter(), monkeypatch).get("/api/v1/broker/kite/login-url")

    assert resp.status_code == 200
    assert resp.json()["url"] == "https://example.com/login"


def test_login_url_is_null_for_a_credential_based_broker(monkeypatch):
    resp = _client(_FakeAdapter(login_url=None), monkeypatch).get("/api/v1/broker/angel_one/login-url")

    assert resp.status_code == 200
    assert resp.json()["url"] is None


def test_login_url_without_credentials_is_a_client_error(monkeypatch):
    resp = _client(_FakeAdapter(BrokerSessionState.UNCONFIGURED), monkeypatch).get("/api/v1/broker/kite/login-url")

    assert resp.status_code == 400
    assert "API key" in resp.json()["detail"]


def test_connect_passes_the_given_fields_to_the_adapter(monkeypatch):
    adapter = _FakeAdapter()

    resp = _client(adapter, monkeypatch).post("/api/v1/broker/kite/connect", json={"request_token": "rt-123"})

    assert resp.status_code == 200
    assert resp.json() == {"state": "ACTIVE", "connected": True}
    assert adapter.connected_with == {"request_token": "rt-123"}


def test_connect_never_returns_the_access_token(monkeypatch):
    """The browser has no use for a broker token and every reason not to
    hold one."""
    resp = _client(_FakeAdapter(), monkeypatch).post("/api/v1/broker/kite/connect", json={"request_token": "rt-123"})

    assert "access-token-value" not in resp.text


def test_connect_only_sends_the_fields_the_caller_actually_gave(monkeypatch):
    adapter = _FakeAdapter()

    _client(adapter, monkeypatch).post(
        "/api/v1/broker/angel_one/connect",
        json={"client_code": "C1", "password": "p", "totp": "123456"},
    )

    assert adapter.connected_with == {"client_code": "C1", "password": "p", "totp": "123456"}


def test_a_rejected_connection_is_reported_as_a_gateway_failure(monkeypatch):
    resp = _client(_FakeAdapter(fail_connect=True), monkeypatch).post(
        "/api/v1/broker/kite/connect", json={"request_token": "stale"}
    )

    assert resp.status_code == 502


def test_disconnect_forgets_the_cached_token(monkeypatch):
    adapter = _FakeAdapter(BrokerSessionState.ACTIVE)

    resp = _client(adapter, monkeypatch).post("/api/v1/broker/kite/disconnect")

    assert resp.json() == {"state": "NEEDS_LOGIN", "connected": False}
    assert adapter.cleared is True


def test_connect_does_not_wait_for_the_instrument_refresh(monkeypatch):
    """Connecting Kite awaited a refresh of ~60,000 instruments inside the
    request: the call hit Nginx's 60s timeout and the refresh starved the
    worker, so every page's data timed out (504) for minutes (2026-10-05)."""
    import threading

    started, release = threading.Event(), threading.Event()

    async def slow_refresh(adapter, exchanges=("NSE", "BSE")):
        started.set()
        import asyncio
        while not release.is_set():
            await asyncio.sleep(0.01)
        return 0

    monkeypatch.setattr(broker, "refresh_instruments_from_adapter", slow_refresh)
    import time
    threading.Timer(3.0, release.set).start()  # frees a route that (wrongly) waits on the refresh
    began = time.monotonic()
    try:
        resp = _client(_FakeAdapter(), monkeypatch).post("/api/v1/broker/kite/connect", json={"request_token": "rt"})
        assert resp.status_code == 200 and resp.json()["connected"] is True
        assert time.monotonic() - began < 1.5  # answered before the refresh finished
    finally:
        release.set()
