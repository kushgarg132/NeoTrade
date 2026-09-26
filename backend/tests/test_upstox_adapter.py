"""UpstoxAdapter: real REST calls (no SDK) against Upstox's documented v2
API, verified 2026-09-09 against https://upstox.com/developer/api-documentation
(fetched live, no account exists to test against for real -- same posture
as Kite's own session file). Every httpx call is mocked here; nothing in
this file makes a real network request.

Endpoints this adapter uses:
- Authorize:  GET  https://api.upstox.com/v2/login/authorization/dialog
              (response_type=code, client_id, redirect_uri[, state])
- Token:      POST https://api.upstox.com/v2/login/authorization/token
              (form: code, client_id, client_secret, redirect_uri,
              grant_type=authorization_code) -> {"access_token": ...}
- Quote:      GET  https://api.upstox.com/v2/market-quote/quotes
              ?instrument_key=... -> {"data": {key: {"last_price", "ohlc": {...}}}}
- Historical: GET  https://api.upstox.com/v2/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}
              -> {"data": {"candles": [[ts, o, h, l, c, volume, oi], ...]}}
- Instruments: gzip JSON dump at
              https://assets.upstox.com/market-quote/instruments/exchange/{NSE|BSE}.json.gz
              (a static file, not a live API call), each row carrying
              instrument_key, trading_symbol, exchange_token, lot_size,
              tick_size, instrument_type.
"""

import gzip
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.brokers.protocol import BrokerSessionState
from backend.brokers.upstox import UpstoxAdapter
from backend.data.feeds.live_upstox import UpstoxMarketFeed
from backend.instruments.models import Instrument


def _redis():
    store = {}
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: store.get(key))
    redis.set = AsyncMock(side_effect=lambda key, value, ex=None: store.__setitem__(key, value))
    redis.delete = AsyncMock(side_effect=lambda key: store.pop(key, None))
    return redis


def _adapter(redis=None):
    return UpstoxAdapter(
        api_key="client-id", api_secret="client-secret", redirect_uri="https://app.example.com/cb",
        redis=redis or _redis(), user_id="alice",
    )


def _instrument(symbol="RELIANCE"):
    return Instrument(
        exchange="NSE", tradingsymbol=symbol, name=symbol, instrument_token=16927,
        exchange_token=16927, instrument_type="EQ", segment="NSE_EQ", lot_size=1, tick_size=0.05,
    )


async def test_unconfigured_without_credentials():
    adapter = UpstoxAdapter(None, None, None, redis=_redis(), user_id="alice")
    assert await adapter.state() == BrokerSessionState.UNCONFIGURED


async def test_needs_login_when_configured_but_not_connected():
    assert await _adapter().state() == BrokerSessionState.NEEDS_LOGIN


async def test_login_url_carries_client_id_and_redirect_uri():
    url = await _adapter().login_url()
    assert url.startswith("https://api.upstox.com/v2/login/authorization/dialog")
    assert "client_id=client-id" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fcb" in url
    assert "response_type=code" in url


async def test_connect_posts_the_code_and_caches_the_token(monkeypatch):
    adapter = _adapter()
    captured = {}

    async def fake_post(self, url, data=None, **kwargs):
        captured["url"] = url
        captured["data"] = data
        return httpx.Response(200, json={"access_token": "up-tok-123"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    token = await adapter.connect(request_token="auth-code-xyz")

    assert token == "up-tok-123"
    assert captured["url"] == "https://api.upstox.com/v2/login/authorization/token"
    assert captured["data"]["code"] == "auth-code-xyz"
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["client_id"] == "client-id"
    assert captured["data"]["client_secret"] == "client-secret"
    assert await adapter.get_access_token() == "up-tok-123"


async def test_active_after_connecting(monkeypatch):
    adapter = _adapter()

    async def fake_post(self, url, data=None, **kwargs):
        return httpx.Response(200, json={"access_token": "up-tok"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    await adapter.connect(request_token="code")

    assert await adapter.state() == BrokerSessionState.ACTIVE


async def test_quote_resolves_the_instrument_key_and_parses_the_response(monkeypatch):
    redis = _redis()
    await redis.set("broker:alice:upstox:access_token", "up-tok")
    adapter = _adapter(redis)

    scrip = [{
        "segment": "NSE_EQ", "exchange": "NSE", "isin": "INE002A01018",
        "instrument_type": "EQ", "instrument_key": "NSE_EQ|INE002A01018",
        "lot_size": 1, "exchange_token": "2885", "tick_size": 0.05,
        "trading_symbol": "RELIANCE", "name": "RELIANCE INDUSTRIES",
    }]

    async def fake_get(self, url, params=None, **kwargs):
        if "assets.upstox.com" in url:
            return httpx.Response(
                200, content=gzip.compress(json.dumps(scrip).encode()), request=httpx.Request("GET", url),
            )
        assert params["instrument_key"] == "NSE_EQ|INE002A01018"
        return httpx.Response(200, json={"data": {
            "NSE_EQ:RELIANCE": {"last_price": 2500.0, "ohlc": {"open": 2490, "high": 2510, "low": 2480, "close": 2495}, "volume": 1000},
        }}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await adapter.quote(_instrument())

    assert result["last_price"] == 2500.0
    assert result["open"] == 2490


async def test_history_maps_the_candle_array_shape(monkeypatch):
    redis = _redis()
    await redis.set("broker:alice:upstox:access_token", "up-tok")
    adapter = _adapter(redis)

    scrip = [{
        "segment": "NSE_EQ", "exchange": "NSE", "isin": "INE002A01018",
        "instrument_type": "EQ", "instrument_key": "NSE_EQ|INE002A01018",
        "lot_size": 1, "exchange_token": "2885", "tick_size": 0.05,
        "trading_symbol": "RELIANCE", "name": "RELIANCE INDUSTRIES",
    }]

    async def fake_get(self, url, params=None, **kwargs):
        if "assets.upstox.com" in url:
            return httpx.Response(
                200, content=gzip.compress(json.dumps(scrip).encode()), request=httpx.Request("GET", url),
            )
        return httpx.Response(200, json={"data": {"candles": [
            ["2026-09-01T00:00:00+05:30", 100.0, 105.0, 98.0, 102.0, 5000, 0],
        ]}}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    candles = await adapter.history(_instrument(), interval="1d", period="1mo")

    assert len(candles) == 1
    assert candles[0].close == 102.0
    assert candles[0].volume == 5000


async def test_history_rejects_an_unsupported_interval():
    adapter = _adapter()
    with pytest.raises(ValueError):
        await adapter.history(_instrument(), interval="15m", period="1mo")


async def test_instruments_parses_the_gzip_scrip_master(monkeypatch):
    scrip = [{
        "segment": "NSE_EQ", "exchange": "NSE", "isin": "INE002A01018",
        "instrument_type": "EQ", "instrument_key": "NSE_EQ|INE002A01018",
        "lot_size": 1, "exchange_token": "2885", "tick_size": 0.05,
        "trading_symbol": "RELIANCE", "name": "RELIANCE INDUSTRIES",
    }]

    async def fake_get(self, url, **kwargs):
        return httpx.Response(
            200, content=gzip.compress(json.dumps(scrip).encode()), request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await _adapter().instruments(exchanges=("NSE",))

    assert len(result) == 1
    assert result[0].tradingsymbol == "RELIANCE"
    assert result[0].instrument_token == 2885


async def test_ticker_feed_is_none_without_a_session():
    adapter = _adapter()
    assert await adapter.ticker_feed([_instrument()], timeframe="5m", timeframe_seconds=300.0) is None


async def test_ticker_feed_subscribes_by_instrument_key_and_keeps_the_app_token():
    redis = _redis()
    await redis.set("broker:alice:upstox:access_token", "up-tok")
    adapter = _adapter(redis)
    adapter._scrip_cache["NSE"] = {"RELIANCE": {"instrument_key": "NSE_EQ|INE002A01018"}}

    feed = await adapter.ticker_feed(
        [_instrument(), _instrument("NOSUCH")], timeframe="5m", timeframe_seconds=300.0,
    )

    assert isinstance(feed, UpstoxMarketFeed)
    assert feed._token_for_key == {"NSE_EQ|INE002A01018": 16927}
    assert feed._access_token == "up-tok"


async def test_ticker_feed_is_none_when_nothing_resolves():
    redis = _redis()
    await redis.set("broker:alice:upstox:access_token", "up-tok")
    adapter = _adapter(redis)
    adapter._scrip_cache["NSE"] = {}

    assert await adapter.ticker_feed([_instrument()], timeframe="5m", timeframe_seconds=300.0) is None


async def test_disconnect_clears_the_cached_token():
    redis = _redis()
    await redis.set("broker:alice:upstox:access_token", "up-tok")
    adapter = _adapter(redis)

    await adapter.disconnect()

    assert await adapter.get_access_token() is None


def _scrip():
    return [{
        "segment": "NSE_EQ", "exchange": "NSE", "isin": "INE002A01018",
        "instrument_type": "EQ", "instrument_key": "NSE_EQ|INE002A01018",
        "lot_size": 1, "exchange_token": "2885", "tick_size": 0.05,
        "trading_symbol": "RELIANCE", "name": "RELIANCE INDUSTRIES",
    }]


async def test_place_order_posts_mapped_fields(monkeypatch):
    from backend.core.models import Order, Side

    redis = _redis()
    await redis.set("broker:alice:upstox:access_token", "up-tok")
    adapter = _adapter(redis)

    captured = {}

    async def fake_get(self, url, **kwargs):
        return httpx.Response(
            200, content=gzip.compress(json.dumps(_scrip()).encode()), request=httpx.Request("GET", url),
        )

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        captured["url"], captured["json"] = url, json
        return httpx.Response(200, json={"status": "success", "data": {"order_id": "up-order-1"}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    order = Order(id="app-1", symbol="RELIANCE", side=Side.BUY, quantity=10.0, order_type="MARKET", product="MIS")
    broker_order_id = await adapter.place_order(order)

    assert broker_order_id == "up-order-1"
    assert captured["url"] == "https://api-hft.upstox.com/v2/order/place"
    assert captured["json"]["quantity"] == 10
    assert captured["json"]["product"] == "I"
    assert captured["json"]["transaction_type"] == "BUY"
    assert captured["json"]["order_type"] == "MARKET"
    assert captured["json"]["instrument_token"] == "NSE_EQ|INE002A01018"


async def test_cancel_order_sends_delete_with_order_id(monkeypatch):
    adapter = _adapter()
    captured = {}

    async def fake_delete(self, url, headers=None, **kwargs):
        captured["url"] = url
        return httpx.Response(200, json={"status": "success", "data": {"order_id": "up-order-1"}}, request=httpx.Request("DELETE", url))

    monkeypatch.setattr(httpx.AsyncClient, "delete", fake_delete)

    await adapter.cancel_order("up-order-1")

    assert captured["url"] == "https://api-hft.upstox.com/v2/order/cancel?order_id=up-order-1"


async def test_get_order_status_maps_complete_to_filled(monkeypatch):
    adapter = _adapter()

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"data": {
            "order_id": "up-order-1", "status": "complete", "filled_quantity": 10, "average_price": 2500.5,
        }}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    status = await adapter.get_order_status("up-order-1")

    assert status.status == "FILLED"
    assert status.filled_quantity == 10
    assert status.average_price == 2500.5


async def test_get_order_status_maps_rejected(monkeypatch):
    adapter = _adapter()

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"data": {
            "order_id": "up-order-1", "status": "rejected", "filled_quantity": 0, "average_price": 0.0,
        }}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    status = await adapter.get_order_status("up-order-1")

    assert status.status == "REJECTED"


async def test_get_positions_maps_trading_symbol(monkeypatch):
    adapter = _adapter()

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"data": [{
            "trading_symbol": "RELIANCE", "quantity": 10, "average_price": 2500.0,
            "unrealised": 150.0, "realised": 0.0,
        }]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    positions = await adapter.get_positions()

    assert positions["RELIANCE"].quantity == 10
    assert positions["RELIANCE"].unrealized_pnl == 150.0


async def test_get_order_status_null_fields_do_not_raise(monkeypatch):
    """Upstox can return a null (not merely absent) value for a freshly-
    placed, unfilled order -- plain `.get(key, default)` only applies the
    default when the key is absent, so a bare float(data.get(...)) would
    raise TypeError on `"filled_quantity": null`. Same `or 0` guard as
    Angel One's equivalent method (backend/brokers/angel_one.py)."""
    adapter = _adapter()

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"data": {
            "order_id": "up-order-1", "status": "open",
            "filled_quantity": None, "average_price": None,
        }}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    status = await adapter.get_order_status("up-order-1")

    assert status.filled_quantity == 0
    assert status.average_price == 0


async def test_get_positions_null_fields_do_not_raise(monkeypatch):
    adapter = _adapter()

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"data": [{
            "trading_symbol": "RELIANCE", "quantity": None, "average_price": None,
            "unrealised": None, "realised": None,
        }]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    positions = await adapter.get_positions()

    assert positions["RELIANCE"].quantity == 0
    assert positions["RELIANCE"].avg_price == 0
    assert positions["RELIANCE"].realized_pnl == 0
    assert positions["RELIANCE"].unrealized_pnl == 0
