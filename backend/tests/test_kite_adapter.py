"""KiteAdapter: a pure composition of the already-tested
KiteSessionManager/KiteProvider/KiteInstrumentSource/KiteTickerFeed behind
the shared BrokerAdapter interface. No new Kite behavior -- these tests
check the wiring, not re-derive session/provider correctness.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from backend.auth.kite_session import KiteSessionState
from backend.brokers.kite import KiteAdapter
from backend.data.feeds.live_kite import KiteTickerFeed
from backend.instruments.models import Instrument


_TOKEN_KEY = "broker:alice:kite:access_token"


def _redis(cached_token=None):
    """Dict-backed so a set() a test performs is visible to a later get() --
    a static AsyncMock return_value would hide the adapter's own writes."""
    store = {_TOKEN_KEY: cached_token} if cached_token else {}
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: store.get(key))
    redis.set = AsyncMock(side_effect=lambda key, value, ex=None: store.__setitem__(key, value))
    redis.delete = AsyncMock(side_effect=lambda key: store.pop(key, None))
    return redis


def _adapter(redis=None):
    return KiteAdapter(api_key="key", api_secret="secret", redis=redis or _redis(), user_id="alice")


def _instrument(token=101, symbol="RELIANCE"):
    return Instrument(
        exchange="NSE", tradingsymbol=symbol, name=symbol, instrument_token=token,
        exchange_token=token, instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )


async def test_state_delegates_to_the_session_manager():
    adapter = _adapter()
    assert await adapter.state() == KiteSessionState.NEEDS_LOGIN


async def test_login_url_delegates_to_the_session_manager():
    adapter = _adapter()
    with patch("backend.auth.kite_session.KiteConnect") as mock_cls:
        mock_cls.return_value.login_url.return_value = "https://kite.zerodha.com/connect/login?api_key=key&v=3"
        assert (await adapter.login_url()).startswith("https://kite.zerodha.com")


async def test_connect_exchanges_a_request_token():
    adapter = _adapter()
    with patch("backend.auth.kite_session.KiteConnect") as mock_cls:
        mock_cls.return_value.generate_session.return_value = {"access_token": "tok-123"}
        token = await adapter.connect(request_token="rt-1")

    assert token == "tok-123"
    assert await adapter.get_access_token() == "tok-123"


async def test_disconnect_clears_the_cached_token():
    redis = _redis(cached_token="cached")
    adapter = _adapter(redis)
    await adapter.disconnect()
    redis.delete.assert_awaited_once()


async def test_quote_delegates_to_kite_provider():
    """`_client_factory` resolves `KiteConnect` via a local
    `from kiteconnect import KiteConnect` at call time, so the patch target
    is the SDK's own module, not backend.auth.kite_session."""
    adapter = _adapter(_redis(cached_token="tok"))
    with patch("kiteconnect.KiteConnect") as mock_cls:
        mock_cls.return_value.quote.return_value = {
            "NSE:RELIANCE": {"last_price": 2500.0, "ohlc": {"open": 2490, "high": 2510, "low": 2480, "close": 2495}},
        }
        result = await adapter.quote(_instrument())

    assert result["last_price"] == 2500.0


async def test_instruments_delegates_to_kite_instrument_source():
    adapter = _adapter(_redis(cached_token="tok"))
    with patch("backend.instruments.kite_source.KiteInstrumentSource.fetch", new_callable=AsyncMock) as fetch:
        fetch.return_value = [_instrument()]
        result = await adapter.instruments(exchanges=("NSE", "BSE"))

    assert result == [_instrument()]


async def test_ticker_feed_is_none_when_not_active():
    adapter = _adapter(_redis())
    assert await adapter.ticker_feed([_instrument()], timeframe="5m", timeframe_seconds=300.0) is None


async def test_ticker_feed_is_returned_when_active():
    adapter = _adapter(_redis(cached_token="tok"))
    with patch("backend.auth.kite_session.KiteConnect") as mock_cls, patch("kiteconnect.KiteConnect"):
        mock_cls.return_value.profile.return_value = {"user_id": "AB1234"}
        feed = await adapter.ticker_feed([_instrument()], timeframe="5m", timeframe_seconds=300.0)

    assert isinstance(feed, KiteTickerFeed)


async def test_ticker_feed_is_none_without_market_data_permission():
    """A Kite app without the market-data add-on: login works, quotes and the
    WebSocket are refused. No feed, so build_feed falls through to Upstox."""
    from kiteconnect.exceptions import PermissionException

    adapter = _adapter(_redis(cached_token="tok"))
    with patch("backend.auth.kite_session.KiteConnect") as session_cls, patch("kiteconnect.KiteConnect") as client_cls:
        session_cls.return_value.profile.return_value = {"user_id": "AB1234"}
        client_cls.return_value.ltp.side_effect = PermissionException("Insufficient permission for that call.")
        feed = await adapter.ticker_feed([_instrument()], timeframe="5m", timeframe_seconds=300.0)

    assert feed is None
