"""Phase 15.3: a running engine can take on the game plan's new symbols."""

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock

from backend.data.feeds.candle_poll import CandlePollingFeed
from backend.data.feeds.live_kite import KiteTickerFeed
from backend.strategies.intraday.orb_breakout import ORBStrategy
from backend.tests.test_candle_poll_feed import OPEN, _instrument, _Provider


def test_extend_universe_adds_once():
    strategy = ORBStrategy(["TCS"], {})
    strategy.extend_universe(["INFY", "TCS"])
    assert strategy.spec.universe == ["TCS", "INFY"] and strategy._universe == ["TCS", "INFY"]


async def test_polling_feed_catches_an_added_instrument_up_as_warmup():
    clock = {"now": OPEN + timedelta(minutes=12)}

    async def sleep(seconds):
        clock["now"] += timedelta(minutes=5)

    feed = CandlePollingFeed(_Provider(), [_instrument("TCS", 1)], sleep_fn=sleep, now_fn=lambda: clock["now"])
    seen, added = [], False
    async for bar in feed:
        seen.append((bar.instrument_token, bar.warmup))
        if not added and bar.instrument_token == 1 and not bar.warmup:
            assert feed.add([_instrument("INFY", 2)]) is False
            assert feed.symbol_for_token[2] == "INFY"
            added = True
        infy = [w for t, w in seen if t == 2]
        if len(infy) >= 3:
            break
    # Its first poll is a catch-up: every candle but the newest is warmup.
    # (The provider stub shows a new instrument 2 closed candles, then 1 per poll.)
    assert [w for t, w in seen if t == 2][:3] == [True, False, False]


async def test_kite_feed_subscribes_added_tokens():
    kws = MagicMock()
    kws.MODE_FULL = "full"
    feed = KiteTickerFeed(kite_ticker_factory=lambda: kws, instrument_tokens=[1], tick_check_seconds=0.0,
                          sleep_fn=lambda s: asyncio.sleep(0))
    it = feed.__aiter__()
    task = asyncio.ensure_future(it.__anext__())
    await asyncio.sleep(0)
    assert feed.add([_instrument("INFY", 9)]) is True
    kws.subscribe.assert_called_with([9])
    kws.set_mode.assert_called_with("full", [9])
    task.cancel()
