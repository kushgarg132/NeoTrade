"""PollingLiveFeed: yields a Bar per instrument per poll, at the configured
cadence, from a fake MarketDataProvider. `sleep_fn` is injected (recording
calls rather than actually sleeping) so this test has zero real wall-clock
wait, per the task brief."""

import asyncio

from backend.data.feeds.polling_live import PollingLiveFeed
from backend.instruments.models import Instrument


def _instrument(token: int, symbol: str) -> Instrument:
    return Instrument(
        exchange="NSE", tradingsymbol=symbol, name=symbol, instrument_token=token,
        exchange_token=token, instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )


class _FakeProvider:
    def __init__(self):
        self.calls = []

    async def quote(self, instrument):
        self.calls.append(instrument.tradingsymbol)
        return {"last_price": 100.0 + len(self.calls)}

    async def history(self, instrument, interval, period):
        raise NotImplementedError


class _FakeSleeper:
    def __init__(self):
        self.sleep_calls = []

    async def __call__(self, seconds):
        self.sleep_calls.append(seconds)


async def test_yields_one_bar_per_instrument_per_poll():
    provider = _FakeProvider()
    instruments = [_instrument(1, "AAA"), _instrument(2, "BBB")]
    sleeper = _FakeSleeper()
    feed = PollingLiveFeed(provider, instruments, timeframe="1m", poll_interval_seconds=30.0, sleep_fn=sleeper)

    gen = feed.__aiter__()
    bars = [await gen.__anext__() for _ in range(4)]  # 2 instruments x 2 polls

    assert [bar.instrument_token for bar in bars] == [1, 2, 1, 2]
    assert provider.calls == ["AAA", "BBB", "AAA", "BBB"]
    # exactly one sleep happened between the first poll's bars and the second's
    assert sleeper.sleep_calls == [30.0]


async def test_sleeps_between_polls_not_between_instruments_in_same_poll():
    provider = _FakeProvider()
    instruments = [_instrument(1, "AAA"), _instrument(2, "BBB"), _instrument(3, "CCC")]
    sleeper = _FakeSleeper()
    feed = PollingLiveFeed(provider, instruments, timeframe="1m", poll_interval_seconds=5.0, sleep_fn=sleeper)

    gen = feed.__aiter__()
    for _ in range(3):
        await gen.__anext__()

    assert sleeper.sleep_calls == []  # no sleep yet -- first poll's 3 bars all came before any sleep
    await gen.__anext__()  # first bar of the second poll
    assert sleeper.sleep_calls == [5.0]


async def test_bar_uses_ohlc_from_quote_when_present():
    class _OhlcProvider:
        async def quote(self, instrument):
            return {"last_price": 105.0, "open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0, "volume": 500}

    instrument = _instrument(1, "AAA")
    feed = PollingLiveFeed(_OhlcProvider(), [instrument], timeframe="1m", sleep_fn=_FakeSleeper())

    gen = feed.__aiter__()
    bar = await gen.__anext__()

    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (100.0, 110.0, 95.0, 105.0, 500)


async def test_bar_falls_back_to_last_price_when_quote_has_no_ohlc():
    instrument = _instrument(1, "AAA")
    feed = PollingLiveFeed(_FakeProvider(), [instrument], timeframe="1m", sleep_fn=_FakeSleeper())

    gen = feed.__aiter__()
    bar = await gen.__anext__()

    assert bar.open == bar.high == bar.low == bar.close == 101.0
    assert bar.volume == 0.0


async def test_skips_an_instrument_whose_quote_fails():
    # A delisted or renamed symbol (GMRINFRA.NS) must not end the whole run.
    class _OneBadProvider(_FakeProvider):
        async def quote(self, instrument):
            if instrument.tradingsymbol == "BAD":
                raise ValueError("No quote data found for BAD.NS")
            return await super().quote(instrument)

    instruments = [_instrument(1, "AAA"), _instrument(2, "BAD"), _instrument(3, "CCC")]
    feed = PollingLiveFeed(_OneBadProvider(), instruments, timeframe="1m", sleep_fn=_FakeSleeper())

    gen = feed.__aiter__()
    bars = [await gen.__anext__() for _ in range(4)]

    assert [bar.instrument_token for bar in bars] == [1, 3, 1, 3]
