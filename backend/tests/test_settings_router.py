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

def test_list_strategies_returns_plain_name_list(client, db, monkeypatch):
    monkeypatch.setattr(settings_router, "db", type("_Db", (), {"db": db})())
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
    assert body["providers"][0] == {"provider": "trae", "plan": None, "available": False, "reason": "not_supported", "quotas": [], "pools": []}
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


def test_a_stale_usage_reading_is_served_at_once_and_refreshed_behind(monkeypatch):
    """OmniRoute polls every provider's quota API live on /me/status (3-5 s),
    so the page must not wait on it once there is any earlier reading."""
    import asyncio
    import time

    async def scenario():
        release = asyncio.Event()

        async def slow_get(self, url, **kwargs):
            await release.wait()
            return _FakeStatusResponse()

        monkeypatch.setattr(httpx.AsyncClient, "get", slow_get)
        monkeypatch.setattr(settings_router.settings, "OMNIROUTE_API_KEYS", ["gw-key"])
        settings_router._USAGE_CACHE.clear()
        settings_router._USAGE_CACHE.update(at=time.monotonic() - 3600, body={"key_name": "old"})

        stale = await asyncio.wait_for(settings_router.fetch_usage(), timeout=1)
        assert stale["key_name"] == "old" and stale["refreshing"] is True  # the page asks again
        again = await asyncio.wait_for(settings_router.fetch_usage(), timeout=1)
        assert again["key_name"] == "old"  # one refresh in flight, not one per call

        release.set()
        await settings_router._USAGE_REFRESH
        fresh = await settings_router.fetch_usage()
        assert fresh["key_name"] == "AI Stock" and fresh["as_of"] and not fresh.get("refreshing")

    asyncio.run(scenario())


def test_quotas_group_into_pools_by_family_and_window():
    from backend.routers.settings import _pools

    quotas = {
        "gemini-3-flash": {"remainingPercentage": 96.47, "resetAt": "2026-10-04T00:49:42Z"},
        "gemini-3.1-pro-high": {"remainingPercentage": 96.47, "resetAt": "2026-10-04T00:49:42Z"},
        "claude-sonnet-4-6": {"remainingPercentage": 100, "resetAt": "2026-10-04T02:50:22Z"},
        "gpt-oss-120b-medium": {"remainingPercentage": 90, "resetAt": "2026-10-04T02:50:22Z"},
        "gemini_weekly": {"remainingPercentage": 98.31, "resetAt": "2026-10-07T03:46:50Z"},
        "claude_gpt_weekly": {"remainingPercentage": 96.4, "resetAt": "2026-10-10T08:31:54Z"},
        "chat_20706": {"remainingPercentage": 100, "resetAt": None},
        "credit": {"remainingPercentage": 40.55, "resetAt": "2026-11-01T00:00:00Z"},
    }
    pools = {p["label"]: p for p in _pools(quotas)}
    assert set(pools) == {"Gemini", "Claude & GPT", "Gemini · weekly", "Claude & GPT · weekly", "Credit"}
    assert pools["Gemini"]["remaining_pct"] == 96.47 and pools["Gemini"]["models"] == ["gemini-3-flash", "gemini-3.1-pro-high"]
    assert pools["Claude & GPT"]["remaining_pct"] == 90 and pools["Claude & GPT"]["reset_at"] == "2026-10-04T02:50:22Z"
    assert pools["Claude & GPT · weekly"]["remaining_pct"] == 96.4


def test_tiers_can_be_read_set_and_cleared_by_an_admin(db):
    admin = _client(db, _user(role="admin"))
    assert admin.get("/api/v1/settings/omniroute-tiers").json()["tiers"] == {"fast": None, "standard": None, "deep": None}

    assert admin.post("/api/v1/settings/omniroute-tiers", json={"tier": "fast", "model": " agy/gemini-3-flash "}).status_code == 200
    assert admin.get("/api/v1/settings/omniroute-tiers").json()["tiers"]["fast"] == "agy/gemini-3-flash"

    assert admin.post("/api/v1/settings/omniroute-tiers", json={"tier": "fast", "model": None}).status_code == 200
    assert admin.get("/api/v1/settings/omniroute-tiers").json()["tiers"]["fast"] is None


def test_tier_changes_are_admin_only_and_tiers_are_known(client, db):
    assert client.post("/api/v1/settings/omniroute-tiers", json={"tier": "fast", "model": "a/b"}).status_code == 403
    admin = _client(db, _user(role="admin"))
    assert admin.post("/api/v1/settings/omniroute-tiers", json={"tier": "huge", "model": "a/b"}).status_code == 422


def test_catalog_groups_the_gateway_models(client, monkeypatch):
    async def fake_get(self, url, **kwargs):
        return _FakeModelsResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    tree = client.get("/api/v1/settings/omniroute-catalog").json()
    assert [f["key"] for f in tree] == ["gemini", "other"]
    assert tree[0]["lines"][0]["models"][0]["id"] == "antigravity/gemini-2.5-flash"


async def test_feature_usage_reads_each_feature_key_and_flags_80_percent(monkeypatch):
    class _Budgeted(_FakeStatusResponse):
        def __init__(self, used):
            self.used = used

        def json(self):
            body = super().json()
            body["usage"]["cost"] = {"usedUsd": self.used, "limitUsd": 1.0, "resetAt": "2026-10-07T18:30:00.000Z"}
            return body

    async def fake_get(self, url, **kwargs):
        return _Budgeted({"Bearer news-key": 0.85, "Bearer chat-key": 0.2}[kwargs["headers"]["Authorization"]])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(settings_router.settings, "OMNIROUTE_FEATURE_KEYS", {"news": "news-key", "chat": "chat-key"})
    settings_router._FEATURE_USAGE.clear()
    body = await settings_router.fetch_feature_usage()
    assert body["news"] == {"tokens": 17, "used_usd": 0.85, "limit_usd": 1.0, "alert": True}
    assert body["chat"]["alert"] is False and list(body) == ["chat", "news"]


def test_an_admin_switches_an_llm_feature_off_and_on(client, db):
    assert client.post("/api/v1/settings/llm-feature", json={"feature": "news", "enabled": False}).status_code == 403
    admin = _client(db, _user(role="admin"))
    assert admin.post("/api/v1/settings/llm-feature", json={"feature": "telepathy", "enabled": False}).status_code == 422
    assert admin.post("/api/v1/settings/llm-feature", json={"feature": "news", "enabled": False}).json() == {
        "feature": "news", "enabled": False}
    assert admin.get("/api/v1/settings/omniroute-tiers").json()["features_off"] == ["news"]
    admin.post("/api/v1/settings/llm-feature", json={"feature": "news", "enabled": True})
    assert admin.get("/api/v1/settings/omniroute-tiers").json()["features_off"] == []
