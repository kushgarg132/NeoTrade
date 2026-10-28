"""UpstoxAdapter, pinned at the wire: the exact requests it sends Upstox and
how each answer maps onto core.models. Written before the switch to the
official upstox-python SDK and kept unchanged across it, so they hold
whichever HTTP client makes a call (backend/tests/upstox_wire.py fakes both).
No Upstox account exists to test against; nothing here touches a network.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.brokers.protocol import BrokerSessionState
from backend.brokers.upstox import UpstoxAdapter
from backend.core.models import Order, Side
from backend.data.feeds.live_upstox import UpstoxMarketFeed
from backend.instruments.models import Instrument
from backend.tests.upstox_wire import UpstoxWire

KEY = "NSE_EQ|INE002A01018"


def _redis():
    store = {}
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: store.get(key))
    redis.set = AsyncMock(side_effect=lambda key, value, ex=None: store.__setitem__(key, value))
    redis.delete = AsyncMock(side_effect=lambda key: store.pop(key, None))
    redis.store = store
    return redis


def _adapter(redis=None):
    return UpstoxAdapter(
        api_key="client-id", api_secret="client-secret", redirect_uri="https://app.example.com/cb",
        redis=redis or _redis(), user_id="alice",
    )


async def _connected(token="up-tok", user_id="alice"):
    redis = _redis()
    await redis.set(f"broker:{user_id}:upstox:access_token", token)
    return UpstoxAdapter(api_key="client-id", api_secret="client-secret", redirect_uri="https://app.example.com/cb",
                         redis=redis, user_id=user_id)


def _instrument(symbol="RELIANCE"):
    return Instrument(
        exchange="NSE", tradingsymbol=symbol, name=symbol, instrument_token=16927,
        exchange_token=16927, instrument_type="EQ", segment="NSE_EQ", lot_size=1, tick_size=0.05,
    )


def _scrip():
    return [{
        "segment": "NSE_EQ", "exchange": "NSE", "isin": "INE002A01018",
        "instrument_type": "EQ", "instrument_key": KEY,
        "lot_size": 1, "exchange_token": "2885", "tick_size": 0.05,
        "trading_symbol": "RELIANCE", "name": "RELIANCE INDUSTRIES",
    }]


def _bearer(call, token="up-tok"):
    assert call.headers["authorization"] == f"Bearer {token}"
    assert "application/json" in call.headers["accept"]


# -- Session ---------------------------------------------------------------

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


async def test_connect_posts_the_code_and_caches_the_token_until_0330_ist(monkeypatch):
    wire = UpstoxWire(monkeypatch).on("POST", "/v2/login/authorization/token", {"access_token": "up-tok-123"})
    redis = _redis()
    adapter = _adapter(redis)

    assert await adapter.connect(request_token="auth-code-xyz") == "up-tok-123"

    call = wire.last("/v2/login/authorization/token")
    assert (call.method, call.host) == ("POST", "api.upstox.com")
    assert call.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert "authorization" not in call.headers
    assert call.form == {"code": "auth-code-xyz", "client_id": "client-id", "client_secret": "client-secret",
                         "redirect_uri": "https://app.example.com/cb", "grant_type": "authorization_code"}
    assert await adapter.get_access_token() == "up-tok-123"
    assert await adapter.state() == BrokerSessionState.ACTIVE
    ttl = redis.set.await_args.kwargs["ex"]
    assert 0 < ttl <= 24 * 3600


async def test_a_refused_code_raises_an_http_error_and_caches_nothing(monkeypatch):
    UpstoxWire(monkeypatch).on("POST", "/v2/login/authorization/token", {"status": "error"}, status=401)
    redis = _redis()
    with pytest.raises(httpx.HTTPError):
        await _adapter(redis).connect(request_token="bad")
    assert redis.store == {}


async def test_connect_without_client_credentials_is_a_runtime_error():
    with pytest.raises(RuntimeError):
        await UpstoxAdapter("id", None, None, redis=_redis(), user_id="alice").connect(request_token="c")


async def test_disconnect_clears_the_cached_token():
    adapter = await _connected()
    await adapter.disconnect()
    assert await adapter.get_access_token() is None


async def test_each_user_sends_their_own_token(monkeypatch):
    wire = UpstoxWire(monkeypatch).on("GET", "/v2/portfolio/short-term-positions", {"data": []})
    await (await _connected("tok-a", "alice")).get_positions()
    await (await _connected("tok-b", "bob")).get_positions()
    await (await _connected("tok-a", "alice")).get_positions()
    assert [c.headers["authorization"] for c in wire.calls] == ["Bearer tok-a", "Bearer tok-b", "Bearer tok-a"]


# -- Market data -------------------------------------------------------------

async def test_quote_resolves_the_instrument_key_and_parses_the_response(monkeypatch):
    wire = UpstoxWire(monkeypatch).scrip(_scrip()).on("GET", "/v2/market-quote/quotes", {"data": {
        "NSE_EQ:RELIANCE": {"last_price": 2500.0, "ohlc": {"open": 2490, "high": 2510, "low": 2480, "close": 2495},
                            "volume": 1000},
    }})

    result = await (await _connected()).quote(_instrument())

    call = wire.last("/v2/market-quote/quotes")
    assert call.query == {"instrument_key": KEY}
    _bearer(call)
    assert result == {"symbol": "RELIANCE", "last_price": 2500.0, "open": 2490, "high": 2510, "low": 2480,
                      "close": 2495, "volume": 1000}


async def test_quote_without_ohlc_falls_back_to_the_last_price(monkeypatch):
    UpstoxWire(monkeypatch).scrip(_scrip()).on("GET", "/v2/market-quote/quotes", {"data": {
        "NSE_EQ:RELIANCE": {"last_price": 2500.0}}})
    result = await (await _connected()).quote(_instrument())
    assert (result["open"], result["high"], result["low"], result["close"], result["volume"]) == (
        2500.0, 2500.0, 2500.0, 2500.0, 0)


async def test_history_maps_the_candle_array_shape(monkeypatch):
    wire = UpstoxWire(monkeypatch).scrip(_scrip()).on("GET", "/v3/historical-candle/", {"data": {"candles": [
        ["2026-09-02T00:00:00+05:30", 102.0, 106.0, 99.0, 104.0, 6000, 0],
        ["2026-09-01T00:00:00+05:30", 100.0, 105.0, 98.0, 102.0, 5000, 0],
    ]}})

    candles = await (await _connected()).history(_instrument(), interval="1d", period="1mo")

    call = wire.last("/v3/historical-candle/")
    _bearer(call)
    today = datetime.now(timezone.utc).date()
    assert call.path == f"/v3/historical-candle/{KEY}/days/1/{today}/{today - timedelta(days=30)}"
    assert [(c.symbol, c.open, c.high, c.low, c.close, c.adj_close, c.volume) for c in candles] == [
        ("RELIANCE", 100.0, 105.0, 98.0, 102.0, 102.0, 5000),
        ("RELIANCE", 102.0, 106.0, 99.0, 104.0, 104.0, 6000),
    ]


async def test_history_rejects_an_unsupported_interval_or_period():
    adapter = _adapter()
    with pytest.raises(ValueError):
        await adapter.history(_instrument(), interval="4h", period="1mo")
    with pytest.raises(ValueError):
        await adapter.history(_instrument(), interval="1d", period="10y")


async def test_a_year_of_5m_history_comes_in_month_chunks_oldest_first(monkeypatch):
    """Upstox v3 refuses a minute range over a month ('Invalid date range') and
    answers newest first; a 429 is retried, not dropped."""
    import backend.brokers.upstox as upstox

    paths, throttled = [], []

    def candles(call):
        if not throttled:
            throttled.append(call.path)
            return 429, {}
        paths.append(call.path)
        to_date, from_date = call.path.rsplit("/", 2)[-2:]
        return {"data": {"candles": [
            [f"{to_date}T15:25:00+05:30", 2.0, 2.0, 2.0, 2.0, 1, 0],
            [f"{from_date}T09:15:00+05:30", 1.0, 1.0, 1.0, 1.0, 1, 0],
        ]}}

    UpstoxWire(monkeypatch).scrip(_scrip()).on("GET", "/v3/historical-candle/", candles)
    monkeypatch.setattr(upstox.asyncio, "sleep", AsyncMock())

    result = await (await _connected()).history(_instrument(), interval="5m", period="max")

    assert all(p.startswith(f"/v3/historical-candle/{KEY}/minutes/5/") for p in paths)
    spans = [(datetime.fromisoformat(p.rsplit("/", 2)[-2]) - datetime.fromisoformat(p.rsplit("/", 1)[-1])).days
             for p in paths]
    assert len(paths) >= 12 and max(spans) < 31
    earliest = min(datetime.fromisoformat(p.rsplit("/", 1)[-1]) for p in paths)
    assert (datetime.fromisoformat(paths[0].rsplit("/", 2)[-2]) - earliest).days >= 372  # the gate asks for 372
    assert paths[0] == throttled[0]  # the throttled chunk was asked again
    stamps = [c.timestamp for c in result]
    assert stamps == sorted(stamps) and len(result) == 2 * len(paths)


async def test_history_gives_up_after_repeated_429s(monkeypatch):
    import backend.brokers.upstox as upstox

    wire = UpstoxWire(monkeypatch).scrip(_scrip()).on("GET", "/v3/historical-candle/", {}, status=429)
    monkeypatch.setattr(upstox.asyncio, "sleep", AsyncMock())
    with pytest.raises(httpx.HTTPError):
        await (await _connected()).history(_instrument(), interval="1d", period="1mo")
    assert len([c for c in wire.calls if "historical-candle" in c.path]) == upstox._RETRIES_429 + 1


async def test_instruments_parses_the_gzip_scrip_master(monkeypatch):
    UpstoxWire(monkeypatch).scrip(_scrip())

    (result,) = await _adapter().instruments(exchanges=("NSE",))

    assert (result.exchange, result.tradingsymbol, result.name, result.instrument_token, result.exchange_token,
            result.instrument_type, result.segment, result.lot_size, result.tick_size, result.isin) == (
        "NSE", "RELIANCE", "RELIANCE INDUSTRIES", 2885, 2885, "EQ", "NSE_EQ", 1, 0.05, "INE002A01018")


async def test_instruments_keeps_only_cash_equities_of_the_dump(monkeypatch):
    eq = {"segment": "NSE_EQ", "exchange": "NSE", "instrument_type": "EQ", "lot_size": 1, "exchange_token": "2885",
          "tick_size": 0.05, "trading_symbol": "RELIANCE", "name": "RELIANCE INDUSTRIES"}
    index = {"segment": "NSE_INDEX", "exchange": "NSE", "instrument_type": "INDEX", "exchange_token": "26000",
             "trading_symbol": "NIFTY 50", "name": "Nifty 50"}  # no lot_size: used to raise KeyError
    fo = {**eq, "segment": "NSE_FO", "instrument_type": "CE", "lot_size": 75, "exchange_token": "1",
          "trading_symbol": "NIFTY 24000 CE"}
    bse = {**eq, "segment": "BSE_EQ", "exchange": "BSE", "trading_symbol": "RELIANCE-B"}
    UpstoxWire(monkeypatch).scrip([eq, index, fo]).scrip([bse], "BSE")

    result = await _adapter().instruments(exchanges=("NSE", "BSE"))

    assert [(i.exchange, i.tradingsymbol) for i in result] == [("NSE", "RELIANCE"), ("BSE", "RELIANCE-B")]


async def test_ticker_feed_is_none_without_a_session():
    adapter = _adapter()
    assert await adapter.ticker_feed([_instrument()], timeframe="5m", timeframe_seconds=300.0) is None


async def test_ticker_feed_subscribes_by_instrument_key_and_keeps_the_app_token():
    adapter = await _connected()
    adapter._scrip_cache["NSE"] = {"RELIANCE": {"instrument_key": KEY}}

    feed = await adapter.ticker_feed(
        [_instrument(), _instrument("NOSUCH")], timeframe="5m", timeframe_seconds=300.0,
    )

    assert isinstance(feed, UpstoxMarketFeed)
    assert feed._token_for_key == {KEY: 16927}
    assert feed._access_token == "up-tok"
    assert feed._key_for(_instrument()) == KEY  # mid-run add() resolves from the dump
    assert feed._key_for(_instrument("NOSUCH")) is None


async def test_ticker_feed_is_none_when_nothing_resolves():
    adapter = await _connected()
    adapter._scrip_cache["NSE"] = {}
    assert await adapter.ticker_feed([_instrument()], timeframe="5m", timeframe_seconds=300.0) is None


# -- Orders --------------------------------------------------------------------

def _placed(wire):
    wire.scrip(_scrip()).on("POST", "/v2/order/place", {"status": "success", "data": {"order_id": "up-order-1"}})
    return wire


def _order_body(call):
    """The place-order body. `is_amo` (after-market order) is false or absent:
    the SDK's model requires it and sends false, the API's own default."""
    body = dict(call.json)
    assert body.pop("is_amo", False) is False
    return body


async def test_place_order_posts_mapped_fields(monkeypatch):
    wire = _placed(UpstoxWire(monkeypatch))
    order = Order(id="app-1", symbol="RELIANCE", side=Side.BUY, quantity=10.0, order_type="MARKET", product="MIS")

    assert await (await _connected()).place_order(order) == "up-order-1"

    call = wire.last("/v2/order/place")
    assert (call.method, call.host) == ("POST", "api-hft.upstox.com")
    _bearer(call)
    assert _order_body(call) == {
        "quantity": 10, "product": "I", "order_type": "MARKET", "transaction_type": "BUY", "validity": "DAY",
        "price": 0, "instrument_token": KEY, "trigger_price": 0, "disclosed_quantity": 0,
    }


async def test_limit_order_sends_its_price(monkeypatch):
    wire = _placed(UpstoxWire(monkeypatch))
    order = Order(id="a", symbol="RELIANCE", side=Side.SELL, quantity=3, order_type="LIMIT", limit_price=2512.5,
                  product="CNC")
    await (await _connected()).place_order(order)
    body = _order_body(wire.last("/v2/order/place"))
    assert (body["order_type"], body["price"], body["trigger_price"], body["product"], body["transaction_type"]) == (
        "LIMIT", 2512.5, 0, "D", "SELL")


async def test_nrml_maps_to_delivery_and_fractional_quantity_is_whole(monkeypatch):
    wire = _placed(UpstoxWire(monkeypatch))
    order = Order(id="a", symbol="RELIANCE", side=Side.BUY, quantity=7.0, order_type="MARKET", product="NRML")
    await (await _connected()).place_order(order)
    body = _order_body(wire.last("/v2/order/place"))
    assert (body["product"], body["quantity"]) == ("D", 7)


async def test_place_order_refuses_a_symbol_missing_from_the_dump(monkeypatch):
    wire = _placed(UpstoxWire(monkeypatch))
    order = Order(id="a", symbol="NOSUCH", side=Side.BUY, quantity=1, order_type="MARKET")
    with pytest.raises(ValueError, match="not found"):
        await (await _connected()).place_order(order)
    assert not [c for c in wire.calls if c.path == "/v2/order/place"]


async def test_a_rejected_order_raises_an_http_error(monkeypatch):
    UpstoxWire(monkeypatch).scrip(_scrip()).on("POST", "/v2/order/place", {"status": "error"}, status=400)
    order = Order(id="a", symbol="RELIANCE", side=Side.BUY, quantity=1, order_type="MARKET")
    with pytest.raises(httpx.HTTPError):
        await (await _connected()).place_order(order)


async def test_cancel_order_sends_delete_with_order_id(monkeypatch):
    wire = UpstoxWire(monkeypatch).on("DELETE", "/v2/order/cancel", {"status": "success", "data": {"order_id": "u1"}})

    await (await _connected()).cancel_order("up-order-1")

    call = wire.last("/v2/order/cancel")
    assert (call.method, call.host, call.query) == ("DELETE", "api-hft.upstox.com", {"order_id": "up-order-1"})
    _bearer(call)


ORDER_BOOK = {"status": "success", "data": [
    {"order_id": "u1", "trading_symbol": "INFY", "transaction_type": "BUY", "quantity": 10, "price": 1500.0,
     "trigger_price": 0.0, "order_type": "LIMIT", "status": "open"},
    {"order_id": "u2", "tradingsymbol": "TCS", "transaction_type": "SELL", "quantity": 1, "price": 0.0,
     "trigger_price": 3900.0, "order_type": "SL-M", "status": "trigger pending"},
]}


async def test_get_orders_normalises_the_order_book(monkeypatch):
    wire = UpstoxWire(monkeypatch).on("GET", "/v2/order/retrieve-all", ORDER_BOOK)

    orders = await (await _connected()).get_orders()

    _bearer(wire.last("/v2/order/retrieve-all"))
    assert orders == [
        {"order_id": "u1", "symbol": "INFY", "side": "BUY", "quantity": 10.0, "price": 1500.0,
         "trigger_price": 0.0, "order_type": "LIMIT", "status": "open"},
        {"order_id": "u2", "symbol": "TCS", "side": "SELL", "quantity": 1.0, "price": 0.0,
         "trigger_price": 3900.0, "order_type": "SL-M", "status": "trigger pending"},
    ]


async def test_modify_order_keeps_unchanged_fields_from_the_book(monkeypatch):
    wire = (UpstoxWire(monkeypatch).on("GET", "/v2/order/retrieve-all", ORDER_BOOK)
            .on("PUT", "/v2/order/modify", {"status": "success", "data": {"order_id": "u1"}}))
    adapter = await _connected()

    await adapter.modify_order("u1", price=1490.0)
    call = wire.last("/v2/order/modify")
    assert (call.method, call.host) == ("PUT", "api-hft.upstox.com")
    _bearer(call)
    assert call.json == {"order_id": "u1", "validity": "DAY", "disclosed_quantity": 0, "quantity": 10,
                         "price": 1490.0, "trigger_price": 0.0, "order_type": "LIMIT"}

    await adapter.modify_order("u2", quantity=2, trigger_price=3950.0)
    assert wire.last("/v2/order/modify").json == {
        "order_id": "u2", "validity": "DAY", "disclosed_quantity": 0, "quantity": 2,
        "price": 0.0, "trigger_price": 3950.0, "order_type": "SL-M"}


async def test_modify_order_refuses_an_order_not_in_the_book(monkeypatch):
    UpstoxWire(monkeypatch).on("GET", "/v2/order/retrieve-all", ORDER_BOOK)
    with pytest.raises(ValueError, match="No order"):
        await (await _connected()).modify_order("nope", price=1.0)


@pytest.mark.parametrize("raw, mapped", [
    ("complete", "FILLED"), ("rejected", "REJECTED"), ("cancelled", "CANCELLED"), ("open", "ACKNOWLEDGED"),
    ("trigger pending", "ACKNOWLEDGED"),
])
async def test_get_order_status_maps_upstox_states(monkeypatch, raw, mapped):
    wire = UpstoxWire(monkeypatch).on("GET", "/v2/order/details", {"data": {
        "order_id": "up-order-1", "status": raw, "filled_quantity": 10, "average_price": 2500.5}})

    status = await (await _connected()).get_order_status("up-order-1")

    call = wire.last("/v2/order/details")
    assert call.query == {"order_id": "up-order-1"}
    _bearer(call)
    assert (status.broker_order_id, status.status, status.filled_quantity, status.average_price) == (
        "up-order-1", mapped, 10, 2500.5)


async def test_get_order_status_null_fields_do_not_raise(monkeypatch):
    """Upstox can return null (not merely absent) for a freshly placed,
    unfilled order."""
    UpstoxWire(monkeypatch).on("GET", "/v2/order/details", {"data": {
        "order_id": "up-order-1", "status": "open", "filled_quantity": None, "average_price": None}})
    status = await (await _connected()).get_order_status("up-order-1")
    assert (status.filled_quantity, status.average_price) == (0, 0)


# -- Portfolio -------------------------------------------------------------------

async def test_get_positions_maps_symbol_pnl_exchange_and_product(monkeypatch):
    wire = UpstoxWire(monkeypatch).on("GET", "/v2/portfolio/short-term-positions", {"data": [
        {"trading_symbol": "SBIN", "exchange": "NSE", "product": "I", "quantity": 10, "average_price": 800,
         "unrealised": 150.0, "realised": 20.0},
        {"trading_symbol": "TCS", "exchange": "NSE_EQ", "product": "D", "quantity": 1, "average_price": 4000},
        {"trading_symbol": "NIFTYFUT", "exchange": "NSE_FO", "product": "D", "quantity": -50, "average_price": 1},
    ]})

    positions = await (await _connected()).get_positions()

    _bearer(wire.last("/v2/portfolio/short-term-positions"))
    sbin, tcs, fut = positions["SBIN"], positions["TCS"], positions["NIFTYFUT"]
    assert (sbin.quantity, sbin.avg_price, sbin.unrealized_pnl, sbin.realized_pnl, sbin.exchange, sbin.product) == (
        10, 800, 150.0, 20.0, "NSE", "MIS")
    assert (tcs.exchange, tcs.product) == ("NSE", "CNC")
    assert (fut.exchange, fut.quantity) == ("NSE_FO", -50)


async def test_get_positions_null_fields_do_not_raise(monkeypatch):
    UpstoxWire(monkeypatch).on("GET", "/v2/portfolio/short-term-positions", {"data": [{
        "trading_symbol": "RELIANCE", "quantity": None, "average_price": None, "unrealised": None, "realised": None}]})
    pos = (await (await _connected()).get_positions())["RELIANCE"]
    assert (pos.quantity, pos.avg_price, pos.realized_pnl, pos.unrealized_pnl, pos.product) == (0, 0, 0, 0, None)


async def test_get_holdings_maps_rows_and_skips_empty_ones(monkeypatch):
    wire = UpstoxWire(monkeypatch).on("GET", "/v2/portfolio/long-term-holdings", {"data": [
        {"isin": "INE002A01018", "company_name": "RELIANCE INDUSTRIES", "trading_symbol": "RELIANCE",
         "exchange": "NSE", "quantity": 10, "t1_quantity": 2, "average_price": 2400.0, "last_price": 2900.0,
         "close_price": 2880.0},
        {"isin": "INF0", "company_name": "NIPPON NIFTY BEES", "tradingsymbol": "NIFTYBEES", "exchange": "NSE",
         "quantity": 5, "average_price": 250.0, "last_price": None, "close_price": 0},
        {"isin": "INE1", "company_name": "SOLD", "trading_symbol": "GONE", "quantity": 0, "average_price": 1.0},
    ]})

    holdings = await (await _connected()).get_holdings()

    _bearer(wire.last("/v2/portfolio/long-term-holdings"))
    assert [h.model_dump() for h in holdings] == [
        {"symbol": "RELIANCE", "isin": "INE002A01018", "name": "RELIANCE INDUSTRIES", "exchange": "NSE",
         "kind": "STOCK", "quantity": 10.0, "avg_price": 2400.0, "last_price": 2900.0, "close_price": 2880.0,
         "broker": "upstox"},
        {"symbol": "NIFTYBEES", "isin": "INF0", "name": "NIPPON NIFTY BEES", "exchange": "NSE",
         "kind": "ETF", "quantity": 5.0, "avg_price": 250.0, "last_price": None, "close_price": None,
         "broker": "upstox"},
    ]


async def test_get_trades_maps_todays_fills(monkeypatch):
    wire = UpstoxWire(monkeypatch).on("GET", "/v2/order/trades/get-trades-for-day", {"data": [
        {"exchange": "NSE", "tradingsymbol": "INFY", "transaction_type": "BUY", "quantity": 2, "order_id": "o1",
         "trade_id": "t1", "average_price": 1500.0, "exchange_timestamp": "2026-09-01 11:00:00"},
        {"exchange": "BSE", "trading_symbol": "TCS", "transaction_type": "SELL", "quantity": 1, "order_id": None,
         "trade_id": 7, "average_price": 4000.0, "order_timestamp": "2026-09-01 09:30:00"},
    ]})

    trades = await (await _connected()).get_trades()

    _bearer(wire.last("/v2/order/trades/get-trades-for-day"))
    ist = lambda h, m: datetime(2026, 9, 1, h, m, tzinfo=timezone(timedelta(hours=5, minutes=30)))  # noqa: E731
    assert [(t.trade_id, t.order_id, t.symbol, t.exchange, t.side, t.quantity, t.price, t.traded_at) for t in trades] == [
        ("t1", "o1", "INFY", "NSE", Side.BUY, 2.0, 1500.0, ist(11, 0)),
        ("7", "", "TCS", "BSE", Side.SELL, 1.0, 4000.0, ist(9, 30)),
    ]


async def test_trade_history_pages_both_segments_and_names_options(monkeypatch):
    def row(tid, segment, **extra):
        return {"exchange": "NSE", "segment": segment, "option_type": "", "quantity": 5, "amount": 0, "trade_id": tid,
                "trade_date": "2026-08-14", "transaction_type": "BUY", "scrip_name": "", "strike_price": "",
                "expiry": "", "price": 100.0, "isin": "", "symbol": "INFY", "instrument_token": "", **extra}

    pages = {
        ("EQ", "1"): ([row("e1", "EQ")], 2),
        ("EQ", "2"): ([row("e2", "EQ", transaction_type="SELL", trade_date="14-08-2026")], 2),
        ("FO", "1"): ([row("f1", "FO", symbol="NIFTY", option_type="CE", strike_price="25100.0",
                           expiry="2026-08-28", exchange="NFO")], 1),
    }

    def page(call):
        data, total = pages[(call.query["segment"], call.query["page_number"])]
        return {"status": "success", "data": data,
                "metaData": {"page": {"page_number": int(call.query["page_number"]), "total_pages": total}}}

    wire = UpstoxWire(monkeypatch).on("GET", "/v2/charges/historical-trades", page)

    trades = await (await _connected()).get_trade_history(date(2026, 8, 1), date(2026, 8, 31))

    queries = [c.query for c in wire.calls]
    assert {(q["segment"], q["page_number"]) for q in queries} == set(pages)
    assert all((q["start_date"], q["end_date"], q["page_size"]) == ("2026-08-01", "2026-08-31", "100")
               for q in queries)
    _bearer(wire.calls[0])
    by_id = {t.trade_id: t for t in trades}
    assert by_id["e2"].side == Side.SELL and by_id["e1"].symbol == "INFY"
    assert by_id["e1"].traded_at == by_id["e2"].traded_at == datetime(2026, 8, 14, 3, 45, tzinfo=timezone.utc)
    assert (by_id["e1"].quantity, by_id["e1"].price, by_id["e1"].order_id) == (5.0, 100.0, "")
    assert by_id["f1"].symbol == "NIFTY 25100 CE 2026-08-28" and by_id["f1"].exchange == "NFO"


# -- Errors ----------------------------------------------------------------------

async def test_an_unreachable_upstox_is_an_http_error(monkeypatch):
    """The options router turns httpx.HTTPError into a 502; every call keeps raising one."""
    UpstoxWire(monkeypatch).down()
    with pytest.raises(httpx.HTTPError):
        await (await _connected()).get_positions()


def test_option_route_502_does_not_leak_the_upstream_error():
    import httpx
    from backend.routers.options import _upstream

    err = _upstream(httpx.HTTPError("https://api.upstox.com/v2?token=SECRET"))
    assert err.status_code == 502 and "SECRET" not in err.detail
