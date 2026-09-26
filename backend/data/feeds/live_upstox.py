"""DataFeed over Upstox's v3 market-data WebSocket.

Real API surface, from the official upstox-python SDK
(upstox_client/feeder/market_data_feeder_v3.py and
proto/MarketDataFeedV3.proto, read 2026-09-26; upstox.com itself is not
reachable from the build environment):

- Connect:   wss://api.upstox.com/v3/feed/market-data-feed with header
  `Authorization: Bearer <access_token>`.
- Subscribe: one *binary* frame holding UTF-8 JSON
  {"guid": ..., "method": "sub", "data": {"mode": "full", "instrumentKeys": [...]}}.
  Keys are Upstox instrument_keys (e.g. "NSE_EQ|INE002A01018"), not numeric tokens.
- Messages:  binary protobuf `FeedResponse`. Only the fields this feed needs
  are decoded, by hand, so the backend carries no protobuf dependency:

    FeedResponse   { Type type = 1; map<string, Feed> feeds = 2; int64 currentTs = 3; ... }
    Feed           { oneof { LTPC ltpc = 1; FullFeed fullFeed = 2;
                             FirstLevelWithGreeks firstLevelWithGreeks = 3; } ... }
    FullFeed       { oneof { MarketFullFeed marketFF = 1; IndexFullFeed indexFF = 2; } }
    MarketFullFeed { LTPC ltpc = 1; ...; int64 vtt = 6;  /* volume traded today */ ... }
    IndexFullFeed  { LTPC ltpc = 1; ... }
    FirstLevelWithGreeks { LTPC ltpc = 1; ...; int64 vtt = 4; ... }
    LTPC           { double ltp = 1; ... }

`vtt` is cumulative for the day, the same shape as Kite's `volume_traded`,
so bars come out of the shared TickBarAggregator exactly as Kite's do.

Unlike KiteTicker this runs on the event loop itself (the `websockets`
asyncio client), so no thread handoff. The SDK reconnects for Kite; here
`_stream` does: any drop is retried with capped backoff while the bar
flush keeps running, emitting flat bars at the last close meanwhile.
"""

import asyncio
import json
import logging
import struct
import uuid
from typing import AsyncIterator, Callable, Optional

from backend.core.models import Bar
from backend.data.feeds.tick_bars import TickBarAggregator

logger = logging.getLogger(__name__)

FEED_URL = "wss://api.upstox.com/v3/feed/market-data-feed"
_MAX_BACKOFF_SECONDS = 30.0


# -- Minimal protobuf wire-format reader -------------------------------------

def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _fields(buf: bytes):
    """Yield (field_number, wire_type, value) for one message. Length-delimited
    values come back as bytes, fixed64 as raw 8 bytes, varints as int."""
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 0x7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 1:
            value, pos = buf[pos:pos + 8], pos + 8
        elif wire == 2:
            length, pos = _varint(buf, pos)
            value, pos = buf[pos:pos + length], pos + length
        elif wire == 5:
            value, pos = buf[pos:pos + 4], pos + 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        yield number, wire, value


def _ltp(ltpc: bytes) -> Optional[float]:
    for number, wire, value in _fields(ltpc):
        if number == 1 and wire == 1:
            return struct.unpack("<d", value)[0]
    return None


def _sub(buf: bytes, number: int) -> Optional[bytes]:
    for n, wire, value in _fields(buf):
        if n == number and wire == 2:
            return value
    return None


def _varint_field(buf: bytes, number: int) -> Optional[int]:
    for n, wire, value in _fields(buf):
        if n == number and wire == 0:
            return value
    return None


def _tick_from_feed(feed: bytes) -> Optional[tuple[float, Optional[int]]]:
    """(last_price, cumulative volume or None) from one `Feed`."""
    ltpc = _sub(feed, 1)
    if ltpc is not None:
        return (price, None) if (price := _ltp(ltpc)) is not None else None

    full = _sub(feed, 2)
    if full is not None:
        market = _sub(full, 1)
        if market is not None:
            inner = _sub(market, 1)
            price = _ltp(inner) if inner is not None else None
            return (price, _varint_field(market, 6)) if price is not None else None
        index = _sub(full, 2)
        if index is not None:
            inner = _sub(index, 1)
            price = _ltp(inner) if inner is not None else None
            return (price, None) if price is not None else None
        return None

    greeks = _sub(feed, 3)
    if greeks is not None:
        inner = _sub(greeks, 1)
        price = _ltp(inner) if inner is not None else None
        return (price, _varint_field(greeks, 4)) if price is not None else None
    return None


def decode_feed_response(buf: bytes) -> dict[str, tuple[float, Optional[int]]]:
    """instrument_key -> (last_price, cumulative volume or None) for every
    feed in one `FeedResponse`. A market_info message has no feeds and
    decodes to {}."""
    ticks = {}
    for number, wire, entry in _fields(buf):
        if number != 2 or wire != 2:
            continue
        key, feed = None, None
        for n, w, value in _fields(entry):
            if n == 1 and w == 2:
                key = value.decode("utf-8")
            elif n == 2 and w == 2:
                feed = value
        if key is None or feed is None:
            continue
        tick = _tick_from_feed(feed)
        if tick is not None:
            ticks[key] = tick
    return ticks


def subscribe_request(instrument_keys: list[str], mode: str = "full") -> bytes:
    return json.dumps({
        "guid": str(uuid.uuid4()),
        "method": "sub",
        "data": {"mode": mode, "instrumentKeys": instrument_keys},
    }).encode("utf-8")


# -- The feed ----------------------------------------------------------------

def _default_connect(access_token: str):
    from websockets.asyncio.client import connect

    return connect(FEED_URL, additional_headers={"Authorization": f"Bearer {access_token}"})


class UpstoxMarketFeed(TickBarAggregator):
    def __init__(
        self,
        access_token: str,
        token_for_key: dict[str, int],
        timeframe: str = "1m",
        timeframe_seconds: float = 60.0,
        tick_check_seconds: float = 1.0,
        now_fn: Callable[[], float] = None,
        sleep_fn: Callable[[float], "asyncio.Future"] = asyncio.sleep,
        connect_fn: Callable[[str], object] = _default_connect,
    ) -> None:
        """`token_for_key` maps each Upstox instrument_key to the
        instrument_token the rest of the app knows it by; bars carry the
        latter."""
        super().__init__(timeframe, timeframe_seconds, tick_check_seconds, now_fn, sleep_fn)
        self._access_token = access_token
        self._token_for_key = token_for_key
        self._connect_fn = connect_fn

    def on_message(self, message: bytes) -> None:
        ticks = []
        for key, (price, volume) in decode_feed_response(message).items():
            token = self._token_for_key.get(key)
            if token is None:
                continue
            tick = {"instrument_token": token, "last_price": price}
            if volume is not None:
                tick["volume_traded"] = volume
            ticks.append(tick)
        if ticks:
            self._ingest(ticks)

    async def _stream(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with self._connect_fn(self._access_token) as ws:
                    await ws.send(subscribe_request(list(self._token_for_key)))
                    backoff = 1.0
                    async for message in ws:
                        if isinstance(message, bytes):
                            try:
                                self.on_message(message)
                            except Exception:
                                logger.exception("upstox feed: could not decode a message")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("upstox feed dropped (%s); reconnecting in %.0fs", exc, backoff)
            await self._sleep_fn(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)

    async def __aiter__(self) -> AsyncIterator[Bar]:
        stream = asyncio.create_task(self._stream())
        try:
            while True:
                await self._sleep_fn(self._tick_check_seconds)
                for bar in self._flush_due_windows(self._now_fn()):
                    yield bar
        finally:
            stream.cancel()
