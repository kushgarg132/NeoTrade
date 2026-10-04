"""Each broker account has a role -- the AI's (autopilot) or the user's own --
and orders reach only the account whose role they are for. No fallback."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.brokers import roles
from backend.brokers.protocol import BrokerSessionState
from backend.prefs import PrefsStore
from backend.routers import settings as settings_router


class _Fake:
    def __init__(self, name, state):
        self.name, self._state = name, state

    async def state(self):
        return self._state


def test_validate_roles_allows_one_ai_and_known_brokers():
    assert roles.validate_roles({"kite": "ai", "upstox": "mine"}) == {"kite": "ai", "upstox": "mine"}
    for bad in ({"kite": "ai", "upstox": "ai"}, {"zerodha": "ai"}, {"kite": "boss"}):
        with pytest.raises(ValueError):
            roles.validate_roles(bad)
    assert roles.brokers_for({"kite": "ai", "upstox": "mine"}, "mine") == {"upstox"}


async def test_adapter_for_returns_only_the_brokers_role_and_never_falls_back(monkeypatch):
    states = {"kite": BrokerSessionState.ACTIVE, "upstox": BrokerSessionState.ACTIVE}

    async def get_adapter(broker, user_id, credentials, redis):
        return _Fake(broker, states[broker])

    monkeypatch.setattr(roles, "get_broker_adapter", get_adapter)
    mapping = {"kite": "ai", "upstox": "mine"}
    assert (await roles.adapter_for("alice", "ai", None, roles=mapping)).name == "kite"
    assert (await roles.adapter_for("alice", "mine", None, roles=mapping)).name == "upstox"

    states["kite"] = BrokerSessionState.NEEDS_LOGIN
    with pytest.raises(roles.RoleUnavailable) as err:
        await roles.adapter_for("alice", "ai", None, roles=mapping)
    assert "kite" in err.value.reason.lower()
    with pytest.raises(roles.RoleUnavailable):
        await roles.adapter_for("alice", "ai", None, roles={"upstox": "mine"})  # no AI account at all


def _client(db):
    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id="alice", google_sub="g", email="a@x.io", name="A", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    app.dependency_overrides[settings_router.get_prefs_store] = lambda: PrefsStore(db)
    return TestClient(app)


def test_put_preferences_rejects_two_ai_accounts():
    client = _client(AsyncMongoMockClient()["test_db"])
    resp = client.put("/api/v1/settings/preferences", json={"broker_roles": {"kite": "ai", "upstox": "ai"}})
    assert resp.status_code == 422


def test_switching_kite_off_ai_disables_autopilot():
    db = AsyncMongoMockClient()["test_db"]
    client = _client(db)
    client.put("/api/v1/settings/preferences", json={"broker_roles": {"kite": "ai"}, "autopilot_enabled": True})
    body = client.put("/api/v1/settings/preferences", json={"broker_roles": {"kite": "mine"}}).json()
    assert body["broker_roles"] == {"kite": "mine"} and body["autopilot_enabled"] is False


def test_autopilot_log_endpoint_lists_newest_first(monkeypatch):
    import asyncio
    from datetime import timedelta

    db = AsyncMongoMockClient()["test_db"]
    from backend.database import db as global_db
    monkeypatch.setattr(global_db, "db", db)
    t0 = datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc)
    asyncio.run(db["autopilot_log"].insert_many([
        {"user_id": "alice", "at": t0, "symbol": "INFY", "status": "FILLED"},
        {"user_id": "alice", "at": t0 + timedelta(minutes=5), "symbol": "TCS", "status": "REFUSED"},
        {"user_id": "bob", "at": t0, "symbol": "SBIN", "status": "FILLED"},
    ]))
    rows = _client(db).get("/api/v1/settings/autopilot/log").json()["rows"]
    assert [r["symbol"] for r in rows] == ["TCS", "INFY"]
