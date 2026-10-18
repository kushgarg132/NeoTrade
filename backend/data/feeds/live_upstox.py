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
- Messages:  binary protobuf `FeedResponse`, decoded with the SDK's generated
  MarketDataFeedV3_pb2. A tick is Feed.ltpc, fullFeed.marketFF/indexFF or
  firstLevelWithGreeks: its ltpc.ltp, plus vtt (volume traded today) where
  the message has one.

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
import uuid
from typing import AsyncIterator, Callable, Optional

from upstox_client.feeder.proto.MarketDataFeedV3_pb2 import FeedResponse

from backend.core.models import Bar
from backend.data.feeds.tick_bars import TickBarAggregator

logger = logging.getLogger(__name__)

FEED_URL = "wss://api.upstox.com/v3/feed/market-data-feed"
_MAX_BACKOFF_SECONDS = 30.0


def _tick(feed) -> Optional[tuple[float, Optional[int]]]:
    """(last_price, cumulative volume or None) from one `Feed`. proto3 leaves
    zeros off the wire, so 0 reads as absent: no price is no tick, and no vtt
    (nothing traded yet) is no volume."""
    kind = feed.WhichOneof("FeedUnion")
    if kind == "ltpc":
        ltpc, vtt = feed.ltpc, None
    elif kind == "fullFeed" and feed.fullFeed.WhichOneof("FullFeedUnion") == "marketFF":
        ltpc, vtt = feed.fullFeed.marketFF.ltpc, feed.fullFeed.marketFF.vtt
    elif kind == "fullFeed" and feed.fullFeed.WhichOneof("FullFeedUnion") == "indexFF":
        ltpc, vtt = feed.fullFeed.indexFF.ltpc, None
    elif kind == "firstLevelWithGreeks":
        ltpc, vtt = feed.firstLevelWithGreeks.ltpc, feed.firstLevelWithGreeks.vtt
    else:
        return None
    return (ltpc.ltp, vtt or None) if ltpc.ltp else None


def decode_feed_response(buf: bytes) -> dict[str, tuple[float, Optional[int]]]:
    """instrument_key -> (last_price, cumulative volume or None) for every
    feed in one `FeedResponse`. A market_info message has no feeds and
    decodes to {}."""
    return {key: tick for key, feed in FeedResponse.FromString(buf).feeds.items() if (tick := _tick(feed))}


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
        key_for: Callable[[object], Optional[str]] = lambda instrument: None,
    ) -> None:
        """`token_for_key` maps each Upstox instrument_key to the
        instrument_token the rest of the app knows it by; bars carry the
        latter. `key_for` resolves an Instrument's key for `add`."""
        super().__init__(timeframe, timeframe_seconds, tick_check_seconds, now_fn, sleep_fn)
        self._access_token = access_token
        self._token_for_key = token_for_key
        self._connect_fn = connect_fn
        self._key_for = key_for
        self._ws = None
        self._subscribing: set[asyncio.Task] = set()

    def add(self, instruments) -> bool:
        """Subscribes to more instruments on the open socket (a reconnect
        resubscribes every key). Ticks start now, so the caller backfills the
        day so far (True)."""
        new = []
        for instrument in instruments:
            key = self._key_for(instrument)
            if key is None:
                logger.warning("upstox feed: no instrument_key for %s; not added", instrument.tradingsymbol)
            elif key not in self._token_for_key:
                self._token_for_key[key] = instrument.instrument_token
                new.append(key)
        if new and self._ws is not None:
            task = asyncio.get_running_loop().create_task(self._ws.send(subscribe_request(new)))
            self._subscribing.add(task)
            task.add_done_callback(self._subscribing.discard)
        return True

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
                    self._ws = ws
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
            finally:
                self._ws = None
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
