"""DataFeed backed by `kiteconnect.KiteTicker`, Kite Connect's WebSocket
streaming API (https://kite.trade/docs/connect/v3/websocket/). **Not
instantiated or run by anything in this task** -- no live Kite
account/access_token exists in this session, so this class only needs to
exist correctly (verified against the real pykiteconnect 5.2.1 source,
cited inline below) plus pass unit tests that feed it synthetic ticks
through mocked callbacks. `backend.data.feeds.polling_live.PollingLiveFeed`
is what actually runs today; swapping it for this class later is a one-line
change since both implement the same `DataFeed` protocol.

Real API surface this wraps:
- `KiteTicker(api_key, access_token, reconnect=True)` -- `reconnect=True` is
  the SDK's own documented default; this class relies on it rather than
  reimplementing reconnect/backoff.
- `kws.on_ticks = fn` / `kws.on_connect = fn` -- plain callback attributes
  (not registration methods) the SDK invokes: `on_ticks(ws, ticks)` with
  `ticks` a list of dicts (each carrying at least `instrument_token`,
  `last_price`, and, in full mode, `ohlc` + `volume_traded`, per
  `ticker.py::_parse_binary`), `on_connect(ws, response)`.
- `kws.subscribe(tokens)` then `kws.set_mode(KiteTicker.MODE_FULL, tokens)`
  -- full mode is what carries `ohlc`/`volume_traded`, needed for real
  OHLCV bars rather than LTP-only ticks.
- `kws.connect(threaded=True)` -- runs Kite's Twisted-based WebSocket client
  on a background thread and returns immediately; without `threaded=True`
  it blocks the calling thread forever running the reactor. Ticks therefore
  arrive on a thread that is NOT the asyncio event loop's thread -- this
  class hands them over via `loop.call_soon_threadsafe`, never touching
  asyncio state directly from the callback.

Bar aggregation (clock-driven, so a quiet symbol still emits a flat bar)
lives in `backend.data.feeds.tick_bars.TickBarAggregator`, shared with the
Upstox feed.
"""

import asyncio
from typing import AsyncIterator, Callable, Optional

from backend.core.models import Bar
from backend.data.feeds.tick_bars import TickBarAggregator


class KiteTickerFeed(TickBarAggregator):
    def __init__(
        self,
        kite_ticker_factory: Callable[[], "KiteTicker"],  # noqa: F821
        instrument_tokens: list[int],
        timeframe: str = "1m",
        timeframe_seconds: float = 60.0,
        tick_check_seconds: float = 1.0,
        now_fn: Callable[[], float] = None,
        sleep_fn: Callable[[float], "asyncio.Future"] = asyncio.sleep,
    ) -> None:
        super().__init__(timeframe, timeframe_seconds, tick_check_seconds, now_fn, sleep_fn)
        self._kite_ticker_factory = kite_ticker_factory
        self._tokens = instrument_tokens
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # -- SDK callbacks (invoked on the Twisted reactor thread in production,
    # or called directly by tests) --

    def on_ticks(self, ws, ticks: list[dict]) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._ingest, ticks)
        else:
            self._ingest(ticks)

    def on_connect(self, ws, response) -> None:
        ws.subscribe(self._tokens)
        ws.set_mode(ws.MODE_FULL, self._tokens)

    async def __aiter__(self) -> AsyncIterator[Bar]:
        self._loop = asyncio.get_running_loop()
        kws = self._kite_ticker_factory()
        kws.on_ticks = self.on_ticks
        kws.on_connect = self.on_connect
        kws.connect(threaded=True)  # non-blocking: runs the SDK's Twisted reactor on its own thread
        try:
            while True:
                await self._sleep_fn(self._tick_check_seconds)
                for bar in self._flush_due_windows(self._now_fn()):
                    yield bar
        finally:
            kws.close()
