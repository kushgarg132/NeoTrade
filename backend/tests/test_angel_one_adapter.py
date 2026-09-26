"""AngelOneAdapter: real REST calls (no SDK) against Angel One's SmartAPI,
verified 2026-09-09 against the official smartapi-python SDK source
(https://github.com/angel-one/smartapi-python) and its README examples --
the routes and payload shapes below are taken directly from that source,
not guessed. No live Angel One account exists to test against for real,
matching Kite's and Upstox's posture. Every httpx call is mocked here.

Real API surface used (root https://apiconnect.angelone.in):
- Login:  POST /rest/auth/angelbroking/user/v1/loginByPassword
  body {"clientcode", "password", "totp"} -> {"status", "data": {"jwtToken",
  "refreshToken", "feedToken"}}. No redirect/OAuth step at all -- the human
  supplies clientcode + password + a fresh TOTP code from their own
  authenticator app on every connect. Session lasts until midnight IST.
- Quote:  POST /rest/secure/angelbroking/market/v1/quote
  body {"mode": "FULL", "exchangeTokens": {"NSE": ["3045"]}}
- Candle: POST /rest/secure/angelbroking/historical/v1/getCandleData
  body {"exchange", "symboltoken", "interval", "fromdate", "todate"}
  (interval e.g. "ONE_DAY"; from/to as "YYYY-MM-DD HH:MM")
- Every authenticated call needs: Authorization: Bearer {jwtToken},
  X-PrivateKey: {api key}, X-UserType: USER, X-SourceID: WEB,
  Content-type: application/json.
- Instruments: NOT a live API call -- a static JSON dump fetched live
  2026-09-09 from https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json
  (145,599 real rows at fetch time), each row: {token, symbol, name, expiry,
  strike, lotsize, instrumenttype, exch_seg, tick_size, freeze_qty}. Equity
  rows carry a "-EQ" suffixed symbol (e.g. "RELIANCE-EQ").
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.brokers.angel_one import AngelOneAdapter
from backend.brokers.protocol import BrokerSessionState
from backend.instruments.models import Instrument


def _redis():
    store = {}
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: store.get(key))
    redis.set = AsyncMock(side_effect=lambda key, value, ex=None: store.__setitem__(key, value))
    redis.delete = AsyncMock(side_effect=lambda key: store.pop(key, None))
    return redis


def _adapter(redis=None):
    return AngelOneAdapter(api_key="pk-1", api_secret="unused", redis=redis or _redis(), user_id="alice")


def _instrument(symbol="RELIANCE"):
    return Instrument(
        exchange="NSE", tradingsymbol=symbol, name=symbol, instrument_token=2885,
        exchange_token=2885, instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )


_SCRIP = [
    {"token": "2885", "symbol": "RELIANCE-EQ", "name": "RELIANCE", "expiry": "", "strike": "-1.000000",
     "lotsize": "1", "instrumenttype": "", "exch_seg": "NSE", "tick_size": "5.000000"},
]


async def test_unconfigured_without_credentials():
    adapter = AngelOneAdapter(None, None, redis=_redis(), user_id="alice")
    assert await adapter.state() == BrokerSessionState.UNCONFIGURED


async def test_no_redirect_login_url():
    """Angel One's flow has no redirect step -- login_url is always None."""
    assert await _adapter().login_url() is None


async def test_connect_posts_client_code_password_and_totp(monkeypatch):
    adapter = _adapter()
    captured = {}

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(200, json={
            "status": True, "data": {"jwtToken": "jwt-abc", "refreshToken": "rt-1", "feedToken": "ft-1"},
        }, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    token = await adapter.connect(client_code="C123", password="secret", totp="123456")

    assert token == "jwt-abc"
    assert captured["url"] == "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"
    assert captured["json"] == {"clientcode": "C123", "password": "secret", "totp": "123456"}
    assert captured["headers"]["X-PrivateKey"] == "pk-1"
    assert await adapter.get_access_token() == "jwt-abc"


async def test_connect_raises_on_a_failed_login(monkeypatch):
    adapter = _adapter()

    async def fake_post(self, url, json=None, **kwargs):
        return httpx.Response(200, json={"status": False, "message": "Invalid totp"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(RuntimeError, match="Invalid totp"):
        await adapter.connect(client_code="C123", password="secret", totp="000000")


async def test_active_after_connecting(monkeypatch):
    adapter = _adapter()

    async def fake_post(self, url, json=None, **kwargs):
        return httpx.Response(200, json={
            "status": True, "data": {"jwtToken": "jwt", "refreshToken": "rt", "feedToken": "ft"},
        }, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    await adapter.connect(client_code="C123", password="secret", totp="123456")

    assert await adapter.state() == BrokerSessionState.ACTIVE


async def test_quote_resolves_the_symboltoken_and_parses_the_response(monkeypatch):
    redis = _redis()
    await redis.set("broker:alice:angel_one:access_token", "jwt")
    adapter = _adapter(redis)

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json=_SCRIP, request=httpx.Request("GET", url))

    captured = {}

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        captured["json"] = json
        return httpx.Response(200, json={"status": True, "data": {"fetched": [
            {"exchange": "NSE", "tradingSymbol": "RELIANCE-EQ", "symbolToken": "2885",
             "ltp": 2500.0, "open": 2490, "high": 2510, "low": 2480, "close": 2495, "tradeVolume": 1000},
        ]}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await adapter.quote(_instrument())

    assert result["last_price"] == 2500.0
    assert captured["json"]["exchangeTokens"] == {"NSE": ["2885"]}


async def test_history_maps_the_candle_array_shape(monkeypatch):
    redis = _redis()
    await redis.set("broker:alice:angel_one:access_token", "jwt")
    adapter = _adapter(redis)

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json=_SCRIP, request=httpx.Request("GET", url))

    async def fake_post(self, url, json=None, **kwargs):
        assert json["interval"] == "ONE_DAY"
        assert json["symboltoken"] == "2885"
        return httpx.Response(200, json={"status": True, "data": [
            ["2026-09-01T00:00:00+05:30", 100.0, 105.0, 98.0, 102.0, 5000],
        ]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    candles = await adapter.history(_instrument(), interval="1d", period="1mo")

    assert len(candles) == 1
    assert candles[0].close == 102.0


async def test_history_rejects_an_unsupported_interval():
    adapter = _adapter()
    with pytest.raises(ValueError):
        await adapter.history(_instrument(), interval="45m", period="1mo")


async def test_instruments_parses_the_scrip_master_and_strips_the_eq_suffix(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json=_SCRIP, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await _adapter().instruments(exchanges=("NSE",))

    assert len(result) == 1
    assert result[0].tradingsymbol == "RELIANCE"
    assert result[0].instrument_token == 2885


async def test_ticker_feed_is_not_supported_yet():
    adapter = _adapter()
    assert await adapter.ticker_feed([], timeframe="5m", timeframe_seconds=300.0) is None


async def test_disconnect_clears_the_cached_token():
    redis = _redis()
    await redis.set("broker:alice:angel_one:access_token", "jwt")
    adapter = _adapter(redis)

    await adapter.disconnect()

    assert await adapter.get_access_token() is None


async def test_place_order_posts_mapped_fields(monkeypatch):
    from backend.core.models import Order, Side

    adapter = _adapter()
    captured = {}

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        if "placeOrder" in url:
            captured["url"], captured["json"] = url, json
            return httpx.Response(200, json={"status": True, "data": {"orderid": "ao-order-1"}}, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"status": True, "data": {"jwtToken": "tok", "refreshToken": "r", "feedToken": "f"}}, request=httpx.Request("POST", url))

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json=_SCRIP, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    order = Order(id="app-1", symbol="RELIANCE", side=Side.BUY, quantity=10.0, order_type="MARKET", product="MIS")
    broker_order_id = await adapter.place_order(order)

    assert broker_order_id == "ao-order-1"
    assert "placeOrder" in captured["url"]
    assert captured["json"]["transactiontype"] == "BUY"
    assert captured["json"]["producttype"] == "INTRADAY"
    assert captured["json"]["quantity"] == "10"


async def test_cancel_order_posts_variety_and_orderid(monkeypatch):
    adapter = _adapter()
    captured = {}

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        captured["url"], captured["json"] = url, json
        return httpx.Response(200, json={"status": True, "data": {}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    await adapter.cancel_order("ao-order-1")

    assert "cancelOrder" in captured["url"]
    assert captured["json"] == {"variety": "NORMAL", "orderid": "ao-order-1"}


async def test_get_order_status_maps_complete_to_filled(monkeypatch):
    adapter = _adapter()

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"status": True, "data": [
            {"orderid": "ao-order-1", "status": "complete", "filledshares": "10", "averageprice": "2500.5"},
        ]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    status = await adapter.get_order_status("ao-order-1")

    assert status.status == "FILLED"
    assert status.filled_quantity == 10
    assert status.average_price == 2500.5


async def test_get_order_status_unrecognized_value_defaults_acknowledged(monkeypatch):
    adapter = _adapter()

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"status": True, "data": [
            {"orderid": "ao-order-1", "status": "some-new-status", "filledshares": "0", "averageprice": "0"},
        ]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    status = await adapter.get_order_status("ao-order-1")

    assert status.status == "ACKNOWLEDGED"


async def test_get_positions_maps_netqty(monkeypatch):
    adapter = _adapter()

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"status": True, "data": [
            {"tradingsymbol": "RELIANCE-EQ", "netqty": "10", "avgnetprice": "2500.0", "pnl": "150.0"},
        ]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    positions = await adapter.get_positions()

    assert positions["RELIANCE"].quantity == 10
    assert positions["RELIANCE"].unrealized_pnl == 150.0
