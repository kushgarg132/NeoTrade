from datetime import datetime, timezone

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.app_settings import AppSettingsStore
from backend.auth.broker_credentials import BrokerCredentialStore
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.prefs import PrefsStore
from backend.routers import settings as settings_router


def _user(user_id="alice", role="user"):
    return User(
        id=user_id, google_sub=f"sub-{user_id}", email=f"{user_id}@example.com",
        name=user_id.title(), picture=None,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc), role=role,
    )


_USER = _user()


@pytest.fixture
def db():
    return AsyncMongoMockClient()["test_db"]


def _client(db, user=_USER):
    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[settings_router.get_credential_store] = (
        lambda: BrokerCredentialStore(db, Fernet(Fernet.generate_key()))
    )
    app.dependency_overrides[settings_router.get_app_settings_store] = (
        lambda: AppSettingsStore(db)
    )
    app.dependency_overrides[settings_router.get_prefs_store] = (
        lambda: PrefsStore(db)
    )
    return TestClient(app)


@pytest.fixture
def client(db):
    return _client(db)


class _FakeModelsResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [
            {"id": "antigravity/gemini-2.5-flash", "owned_by": "antigravity"},
            {"id": "aug/sonnet5-high", "owned_by": "aug"},
        ]}


def test_list_omniroute_models_returns_stripped_ids(client, monkeypatch):
    async def fake_get(self, url, **kwargs):
        return _FakeModelsResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    resp = client.get("/api/v1/settings/omniroute-models")
    assert resp.status_code == 200
    assert resp.json() == [
        {"id": "antigravity/gemini-2.5-flash"},
        {"id": "aug/sonnet5-high"},
    ]


def test_list_omniroute_models_sends_the_gateway_key(client, monkeypatch):
    seen = {}

    async def fake_get(self, url, **kwargs):
        seen.update(kwargs.get("headers") or {})
        return _FakeModelsResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(settings_router.settings, "OMNIROUTE_API_KEYS", ["gw-key"])

    assert client.get("/api/v1/settings/omniroute-models").status_code == 200
    assert seen.get("Authorization") == "Bearer gw-key"


def test_list_omniroute_models_returns_502_on_gateway_error(client, monkeypatch):
    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    resp = client.get("/api/v1/settings/omniroute-models")
    assert resp.status_code == 502


def test_get_omniroute_model_returns_current_setting(client):
    resp = client.get("/api/v1/settings/omniroute-model")
    assert resp.status_code == 200
    assert "model" in resp.json()


# --- deployment-wide settings are admin-only -------------------------------

def test_a_normal_user_cannot_change_the_deployment_model(client):
    resp = client.post("/api/v1/settings/omniroute-model", json={"model": "aug/sonnet5-high"})
    assert resp.status_code == 403


def test_an_admin_can_change_the_deployment_model(db):
    client = _client(db, user=_user("boss", role="admin"))

    resp = client.post("/api/v1/settings/omniroute-model", json={"model": "aug/sonnet5-high"})
    assert resp.status_code == 200

    assert client.get("/api/v1/settings/omniroute-model").json()["model"] == "aug/sonnet5-high"


def test_setting_the_model_rejects_an_empty_value(db):
    client = _client(db, user=_user("boss", role="admin"))
    resp = client.post("/api/v1/settings/omniroute-model", json={"model": "   "})
    assert resp.status_code == 400


def test_the_settings_router_never_writes_env_files():
    """The .env-rewriting endpoints were the multi-tenancy hole: they mutated
    shared process state from a request that only required being signed in."""
    assert not hasattr(settings_router, "_write_env_vars")
    assert not hasattr(settings_router, "ENV_PATH")


# --- broker credentials are per-user ---------------------------------------

def test_broker_credentials_start_unconfigured(client):
    resp = client.get("/api/v1/settings/broker-credentials?broker=kite")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False, "api_key_masked": None}


def test_saving_broker_credentials_never_echoes_the_secret(client):
    resp = client.post(
        "/api/v1/settings/broker-credentials",
        json={"broker": "kite", "api_key": "abcd1234wxyz", "api_secret": "super-secret"},
    )
    assert resp.status_code == 200
    assert "super-secret" not in resp.text


def test_saved_broker_credentials_are_reported_as_configured_and_masked(client):
    client.post(
        "/api/v1/settings/broker-credentials",
        json={"broker": "kite", "api_key": "abcd1234wxyz", "api_secret": "super-secret"},
    )

    body = client.get("/api/v1/settings/broker-credentials?broker=kite").json()
    assert body["configured"] is True
    assert body["api_key_masked"].endswith("wxyz")
    assert "super-secret" not in str(body)


def test_one_users_broker_credentials_are_invisible_to_another(db):
    _client(db, user=_user("alice")).post(
        "/api/v1/settings/broker-credentials",
        json={"broker": "kite", "api_key": "alice-key", "api_secret": "alice-secret"},
    )

    body = _client(db, user=_user("bob")).get(
        "/api/v1/settings/broker-credentials?broker=kite"
    ).json()
    assert body == {"configured": False, "api_key_masked": None}


def test_broker_credentials_reject_a_blank_secret(client):
    resp = client.post(
        "/api/v1/settings/broker-credentials",
        json={"broker": "kite", "api_key": "abcd", "api_secret": "   "},
    )
    assert resp.status_code == 400


def test_upstox_credentials_carry_a_redirect_uri(client):
    resp = client.post(
        "/api/v1/settings/broker-credentials",
        json={
            "broker": "upstox", "api_key": "ak", "api_secret": "as",
            "extra": "https://app.example.com/callback",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is True


def test_angel_one_credentials_do_not_require_a_secret(client):
    """Angel One's app-level API key is the only long-lived credential; the
    account password and TOTP are supplied fresh at connect time, never
    stored (see backend/brokers/angel_one.py)."""
    resp = client.post(
        "/api/v1/settings/broker-credentials",
        json={"broker": "angel_one", "api_key": "pk-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is True


def test_kite_still_requires_both_key_and_secret(client):
    resp = client.post(
        "/api/v1/settings/broker-credentials",
        json={"broker": "kite", "api_key": "ak"},
    )
    assert resp.status_code == 400


def test_deleting_broker_credentials_disconnects_only_the_caller(db):
    _client(db, user=_user("alice")).post(
        "/api/v1/settings/broker-credentials",
        json={"broker": "kite", "api_key": "alice-key", "api_secret": "alice-secret"},
    )
    _client(db, user=_user("bob")).post(
        "/api/v1/settings/broker-credentials",
        json={"broker": "kite", "api_key": "bob-key", "api_secret": "bob-secret"},
    )

    assert _client(db, user=_user("alice")).delete(
        "/api/v1/settings/broker-credentials?broker=kite"
    ).status_code == 200

    assert _client(db, user=_user("alice")).get(
        "/api/v1/settings/broker-credentials?broker=kite"
    ).json()["configured"] is False
    assert _client(db, user=_user("bob")).get(
        "/api/v1/settings/broker-credentials?broker=kite"
    ).json()["configured"] is True


def test_live_strategies_defaults_to_empty(client):
    resp = client.get("/api/v1/settings/preferences")
    assert resp.status_code == 200
    assert resp.json()["live_strategies"] == []


def test_live_strategies_can_be_updated(client):
    resp = client.put(
        "/api/v1/settings/preferences", json={"live_strategies": ["volume_surge"]},
    )
    assert resp.status_code == 200
    assert resp.json()["live_strategies"] == ["volume_surge"]


# --- strategy names, for the Settings live/paper toggles --------------------

def test_list_strategies_returns_plain_name_list(client):
    resp = client.get("/api/v1/settings/strategies")
    assert resp.status_code == 200
    names = resp.json()
    assert isinstance(names, list)
    assert "volume_surge" in names


def test_strategy_promotion_lists_what_each_strategy_still_needs(client, db, monkeypatch):
    monkeypatch.setattr(settings_router, "db", type("_Db", (), {"db": db})())
    resp = client.get("/api/v1/settings/strategies/promotion")
    assert resp.status_code == 200
    rows = {r["name"]: r for r in resp.json()}
    row = rows["volume_surge"]
    assert row["backtest_passed"] is False and row["eligible"] is False
    assert {c["rule"] for c in row["paper"]["checks"]} == {
        "days", "trades", "net", "profit_factor", "max_drawdown_pct",
    }


def test_strategy_promotion_includes_the_last_backtest_and_the_options_strategy(client, db, monkeypatch):
    import asyncio
    from datetime import datetime, timezone

    from backend.components.shared.models import BacktestResult
    from backend.risk.backtest_gate import BacktestGateStore

    monkeypatch.setattr(settings_router, "db", type("_Db", (), {"db": db})())
    asyncio.run(BacktestGateStore(db).record("orb_breakout", BacktestResult(
        symbol="X", start_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 8, 28, tzinfo=timezone.utc), total_trades=198, win_rate=0.42,
        profit_factor=0.64, total_pnl=-1.0, max_drawdown=0.25, sharpe_ratio=-4.2, trades=[],
    )))
    rows = {r["name"]: r for r in client.get("/api/v1/settings/strategies/promotion").json()}
    assert rows["orb_breakout"]["backtest"]["days"] == 58
    assert rows["orb_breakout"]["backtest"]["trades"] == 198
    assert rows["orb_options"]["backtest"] is None


def test_portfolio_verdicts_default_to_admin_and_only_an_admin_changes_them(db):
    admin = _client(db, user=_user("boss", role="admin"))
    assert admin.get("/api/v1/settings/portfolio-verdicts").json() == {"audience": "admin"}
    assert _client(db).put("/api/v1/settings/portfolio-verdicts", json={"audience": "all"}).status_code == 403
    assert admin.put("/api/v1/settings/portfolio-verdicts", json={"audience": "all"}).json() == {"audience": "all"}
    assert admin.put("/api/v1/settings/portfolio-verdicts", json={"audience": "everyone"}).status_code == 422
    assert admin.get("/api/v1/settings/portfolio-verdicts").json() == {"audience": "all"}


def test_portfolio_limits_are_editable_preferences(client):
    resp = client.put("/api/v1/settings/preferences", json={"portfolio_max_loss_pct": 15, "portfolio_max_weight_pct": 10})
    assert resp.status_code == 200
    assert (resp.json()["portfolio_max_loss_pct"], resp.json()["portfolio_max_weight_pct"]) == (15, 10)
    assert client.put("/api/v1/settings/preferences", json={"portfolio_max_loss_pct": 0}).status_code == 422


def test_model_test_reports_a_working_model(db, monkeypatch):
    from langchain_openai import ChatOpenAI

    calls = {}

    async def fake_ainvoke(self, messages, **kwargs):
        calls["model"] = self.model_name
        return type("R", (), {"content": "OK"})()

    monkeypatch.setattr(ChatOpenAI, "ainvoke", fake_ainvoke)
    monkeypatch.setattr(settings_router.settings, "OMNIROUTE_API_KEYS", ["gw-key"])
    resp = _client(db, _user(role="admin")).post("/api/v1/settings/omniroute-model/test", json={"model": "aug/sonnet5-high"})

    body = resp.json()
    assert resp.status_code == 200 and body["ok"] is True and body["reply"] == "OK"
    assert calls["model"] == "aug/sonnet5-high" and body["latency_ms"] >= 0


def test_model_test_reports_a_gateway_error_as_not_ok(db, monkeypatch):
    from langchain_openai import ChatOpenAI

    async def fake_ainvoke(self, messages, **kwargs):
        raise RuntimeError("Error code: 404 - model not found")

    monkeypatch.setattr(ChatOpenAI, "ainvoke", fake_ainvoke)
    monkeypatch.setattr(settings_router.settings, "OMNIROUTE_API_KEYS", ["gw-key"])
    body = _client(db, _user(role="admin")).post("/api/v1/settings/omniroute-model/test", json={"model": "nope/x"}).json()
    assert body["ok"] is False and "model not found" in body["error"]


def test_model_test_is_admin_only(client):
    assert client.post("/api/v1/settings/omniroute-model/test", json={"model": "a/b"}).status_code == 403


class _FakeStatusResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {
            "apiKey": {"id": "k1", "name": "AI Stock"},
            "usage": {
                "cost": {"usedUsd": 0, "limitUsd": None, "resetAt": "2026-11-01T00:00:00.000Z"},
                "tokens": {"inputTokens": 10, "outputTokens": 5, "reasoningTokens": 2, "totalTokens": 17},
            },
            "accountQuotas": [
                {"provider": "trae", "available": False, "reason": "not_supported"},
                {"provider": "kiro", "plan": "KIRO FREE", "quotas": {
                    "credit": {"usedPercentage": 9.45, "remainingPercentage": 40.55, "resetAt": "2026-11-01T00:00:00.000Z"}}},
            ],
        }


def test_omniroute_usage_is_shaped_for_the_page(db, monkeypatch):
    seen = {}

    async def fake_get(self, url, **kwargs):
        seen["url"], seen["headers"] = url, kwargs.get("headers")
        return _FakeStatusResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(settings_router.settings, "OMNIROUTE_API_KEYS", ["gw-key"])
    settings_router._USAGE_CACHE.clear()
    body = _client(db, _user(role="admin")).get("/api/v1/settings/omniroute-usage").json()

    assert seen["url"].endswith("/me/status") and seen["headers"]["Authorization"] == "Bearer gw-key"
    assert body["key_name"] == "AI Stock"
    assert body["tokens"]["total"] == 17 and body["cost"]["used_usd"] == 0
    assert body["providers"][0] == {"provider": "trae", "plan": None, "available": False, "reason": "not_supported", "quotas": []}
    assert body["providers"][1]["quotas"] == [
        {"name": "credit", "remaining_pct": 40.55, "reset_at": "2026-11-01T00:00:00.000Z"}
    ]


def test_omniroute_usage_is_admin_only(client):
    assert client.get("/api/v1/settings/omniroute-usage").status_code == 403


def test_omniroute_usage_gateway_error_is_502(db, monkeypatch):
    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(settings_router.settings, "OMNIROUTE_API_KEYS", ["gw-key"])
    settings_router._USAGE_CACHE.clear()
    assert _client(db, _user(role="admin")).get("/api/v1/settings/omniroute-usage").status_code == 502
