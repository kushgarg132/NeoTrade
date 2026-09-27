"""Live option chains from the user's Upstox session. Response shapes follow
the official SDK's generated models (OptionStrikeData, PutCallOptionChainData,
MarketData, AnalyticsData); every HTTP call is mocked."""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.brokers.protocol import BrokerSessionState
from backend.brokers.upstox import UpstoxAdapter
from backend.routers import options


def _leg(key, ltp, oi, prev_oi, iv):
    return {"instrument_key": key,
            "market_data": {"ltp": ltp, "volume": 1000, "oi": oi, "close_price": ltp + 5,
                            "bid_price": ltp - 0.5, "bid_qty": 75, "ask_price": ltp + 0.5, "ask_qty": 75,
                            "prev_oi": prev_oi},
            "option_greeks": {"vega": 1.0, "theta": -4.2, "gamma": 0.001, "delta": 0.5, "iv": iv, "pop": 50.0}}


CHAIN = {"status": "success", "data": [
    {"expiry": "2026-09-29", "pcr": 1.2, "strike_price": 25200.0, "underlying_key": "NSE_INDEX|Nifty 50",
     "underlying_spot_price": 25123.45,
     "call_options": _leg("NSE_FO|1", 60.0, 900.0, 800.0, 12.5), "put_options": _leg("NSE_FO|2", 140.0, 700.0, 750.0, 13.1)},
    {"expiry": "2026-09-29", "pcr": 0.9, "strike_price": 25100.0, "underlying_key": "NSE_INDEX|Nifty 50",
     "underlying_spot_price": 25123.45,
     "call_options": _leg("NSE_FO|3", 110.0, 500.0, 400.0, 12.0), "put_options": _leg("NSE_FO|4", 85.0, 600.0, 500.0, 12.8)},
]}
CONTRACTS = {"status": "success", "data": [
    {"expiry": "2026-10-06T00:00:00", "strike_price": 25000.0},
    {"expiry": "2026-09-29T00:00:00", "strike_price": 25000.0},
    {"expiry": "2026-09-29T00:00:00", "strike_price": 25100.0},
]}


@pytest.fixture
def adapter(monkeypatch):
    calls = []

    async def fake_get(self, url, params=None, headers=None):
        calls.append((url, params, headers))
        body = CHAIN if url.endswith("/option/chain") else CONTRACTS
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    a = UpstoxAdapter(api_key="id", api_secret="secret", redirect_uri="https://x/cb", redis=None, user_id="alice")
    a.get_access_token = AsyncMock(return_value="tok")
    a.calls = calls
    return a


@pytest.mark.asyncio
async def test_expiries_come_from_the_contract_list_soonest_first(adapter):
    assert await adapter.option_expiries("NSE_INDEX|Nifty 50") == ["2026-09-29", "2026-10-06"]
    url, params, headers = adapter.calls[0]
    assert url == "https://api.upstox.com/v2/option/contract"
    assert params == {"instrument_key": "NSE_INDEX|Nifty 50"}
    assert headers["Authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_chain_puts_call_and_put_side_by_side_lowest_strike_first(adapter):
    rows = await adapter.option_chain("NSE_INDEX|Nifty 50", "2026-09-29")
    assert adapter.calls[0][1] == {"instrument_key": "NSE_INDEX|Nifty 50", "expiry_date": "2026-09-29"}
    assert [r["strike"] for r in rows] == [25100.0, 25200.0]
    call = rows[0]["call"]
    assert call["ltp"] == 110.0 and call["oi"] == 500.0 and call["oi_change"] == 100.0
    assert call["bid"] == 109.5 and call["ask"] == 110.5 and call["iv"] == 12.0 and call["theta"] == -4.2
    assert rows[1]["put"]["oi_change"] == -50.0


def _client(adapter):
    app = FastAPI()
    app.include_router(options.router, prefix="/api/v1")
    app.dependency_overrides[options.upstox_for] = lambda: adapter
    return TestClient(app)


def test_chain_route_adds_spot_atm_and_total_pcr(adapter):
    body = _client(adapter).get("/api/v1/options/chain", params={"underlying": "NIFTY", "expiry": "2026-09-29"}).json()
    assert body["spot"] == 25123.45
    assert body["atm_strike"] == 25100.0
    assert body["pcr"] == pytest.approx((700 + 600) / (900 + 500))
    assert len(body["strikes"]) == 2


def test_unknown_underlying_is_refused(adapter):
    assert _client(adapter).get("/api/v1/options/expiries", params={"underlying": "AAPL"}).status_code == 422


def test_without_an_upstox_login_the_route_says_connect_upstox(monkeypatch):
    class _LoggedOut:
        async def state(self):
            return BrokerSessionState.NEEDS_LOGIN

    monkeypatch.setattr(options, "get_broker_adapter", AsyncMock(return_value=_LoggedOut()))
    monkeypatch.setattr(options, "get_credential_store", lambda: None)
    app = FastAPI()
    app.include_router(options.router, prefix="/api/v1")
    from backend.auth.dependency import get_current_user
    app.dependency_overrides[get_current_user] = lambda: type("U", (), {"id": "alice"})()

    resp = TestClient(app).get("/api/v1/options/expiries", params={"underlying": "NIFTY"})
    assert resp.status_code == 409
    assert "Connect Upstox" in resp.json()["detail"]


def test_an_upstox_failure_is_a_502(adapter, monkeypatch):
    async def broken(self, url, params=None, headers=None):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx.AsyncClient, "get", broken)
    assert _client(adapter).get("/api/v1/options/expiries", params={"underlying": "NIFTY"}).status_code == 502
