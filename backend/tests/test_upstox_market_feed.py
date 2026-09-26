"""UpstoxMarketFeed: protobuf FeedResponse frames -> ticks -> clock-driven
bars, plus the subscribe frame and reconnect loop. No real WebSocket: the
frames are built here field-by-field from MarketDataFeedV3.proto's field
numbers (quoted in backend/data/feeds/live_upstox.py), and `connect_fn`
returns a fake connection."""

import asyncio
import json
import struct

import pytest

from backend.data.feeds.live_upstox import (
    UpstoxMarketFeed, decode_feed_response, subscribe_request,
)

KEY = "NSE_EQ|INE002A01018"


# -- A tiny protobuf writer, enough to build FeedResponse frames ------------

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _len(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _double(number: int, value: float) -> bytes:
    return _varint(number << 3 | 1) + struct.pack("<d", value)


def _int(number: int, value: int) -> bytes:
    return _varint(number << 3 | 0) + _varint(value)


def _ltpc(ltp: float) -> bytes:
    # ltp=1, ltt=2, ltq=3, cp=4
    return _double(1, ltp) + _int(2, 1_790_000_000_000) + _int(3, 10) + _double(4, ltp - 5)


def _market_full(ltp: float, vtt: int) -> bytes:
    market_ff = _len(1, _ltpc(ltp)) + _double(5, ltp) + _int(6, vtt)  # ltpc, atp, vtt
    return _len(2, _len(1, market_ff))  # Feed.fullFeed -> FullFeed.marketFF


def _index_full(ltp: float) -> bytes:
    return _len(2, _len(2, _len(1, _ltpc(ltp))))  # Feed.fullFeed -> FullFeed.indexFF


def _response(feeds: dict[str, bytes], type_: int = 1) -> bytes:
    body = _int(1, type_) if type_ else b""
    for key, feed in feeds.items():
        body += _len(2, _len(1, key.encode()) + _len(2, feed))
    return body + _int(3, 1_790_000_000_123)


# -- Decoding ---------------------------------------------------------------

def test_decodes_price_and_cumulative_volume_from_a_full_market_feed():
    assert decode_feed_response(_response({KEY: _market_full(2950.5, 1_234_567)})) == {
        KEY: (2950.5, 1_234_567),
    }


def test_decodes_ltpc_only_and_index_feeds_without_volume():
    frame = _response({
        KEY: _len(1, _ltpc(100.25)),
        "NSE_INDEX|Nifty 50": _index_full(25010.0),
    })
    assert decode_feed_response(frame) == {
        KEY: (100.25, None),
        "NSE_INDEX|Nifty 50": (25010.0, None),
    }


def test_decodes_first_level_with_greeks():
    greeks = _len(1, _ltpc(88.0)) + _int(4, 500)  # ltpc, vtt
    assert decode_feed_response(_response({KEY: _len(3, greeks)})) == {KEY: (88.0, 500)}


def test_market_info_message_has_no_ticks():
    market_info = _len(4, _len(1, _len(1, b"NSE_EQ") + _int(2, 2)))
    assert decode_feed_response(_int(1, 2) + market_info) == {}


def test_subscribe_request_is_json_for_full_mode():
    body = json.loads(subscribe_request([KEY]))
    assert body["method"] == "sub"
    assert body["data"] == {"mode": "full", "instrumentKeys": [KEY]}
    assert body["guid"]


# -- Bars -------------------------------------------------------------------

class _FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(0)
        self.t += seconds


def test_messages_become_bars_under_the_app_token():
    clock = _FakeClock(start=0.0)
    feed = UpstoxMarketFeed(
        "tok", {KEY: 16927}, timeframe_seconds=60.0, now_fn=clock.now, sleep_fn=clock.sleep,
    )

    feed.on_message(_response({KEY: _market_full(100.0, 1000)}))
    feed.on_message(_response({KEY: _market_full(104.0, 1300)}))
    feed.on_message(_response({"NSE_EQ|UNKNOWN": _market_full(1.0, 1)}))
    feed.on_message(_response({KEY: _market_full(99.0, 1400)}))
    [bar] = feed._flush_due_windows(60.0)

    assert bar.instrument_token == 16927
    assert (bar.open, bar.high, bar.low, bar.close) == (100.0, 104.0, 99.0, 99.0)
    # First window has no prior cumulative reading to diff against.
    assert bar.volume == 0.0

    feed.on_message(_response({KEY: _market_full(101.0, 1500)}))
    [bar] = feed._flush_due_windows(120.0)
    assert bar.volume == 100.0


# -- Streaming loop ---------------------------------------------------------

class _FakeConnection:
    def __init__(self, messages, fail_after=True):
        self.sent = []
        self._messages = messages
        self._fail_after = fail_after

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, data):
        self.sent.append(data)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for message in self._messages:
            yield message
        if self._fail_after:
            raise ConnectionError("dropped")


async def test_stream_subscribes_ingests_and_reconnects_after_a_drop():
    connections = [
        _FakeConnection([_response({KEY: _market_full(100.0, 10)}), "a text frame is ignored"]),
        _FakeConnection([_response({KEY: _market_full(101.0, 20)})]),
    ]
    tokens_used, sleeps = [], []
    reconnected = asyncio.Event()

    def connect(token):
        tokens_used.append(token)
        if len(tokens_used) == 2:
            reconnected.set()
        return connections[min(len(tokens_used), 2) - 1]

    async def sleep(seconds):
        sleeps.append(seconds)
        await asyncio.sleep(0)

    feed = UpstoxMarketFeed("tok", {KEY: 16927}, now_fn=lambda: 0.0, sleep_fn=sleep, connect_fn=connect)
    task = asyncio.create_task(feed._stream())
    await asyncio.wait_for(reconnected.wait(), timeout=1)
    for _ in range(5):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert tokens_used[:2] == ["tok", "tok"]
    assert json.loads(connections[0].sent[0])["data"]["instrumentKeys"] == [KEY]
    assert sleeps[0] == 1.0  # backoff after the first drop
    assert feed._windows[16927].close == 101.0
