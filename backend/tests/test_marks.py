"""Mark prices are best-effort.

The P&L cards are the first thing read on the statement, so a slow or broken
quote provider must cost the unrealised line and nothing else. An absent mark
is already treated as "no mark" downstream; a hung request would instead stall
the whole page.
"""

import asyncio
import json
import time

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend import marks
from backend.instruments.models import Instrument


def _instrument(symbol: str) -> Instrument:
    return Instrument(
        exchange="NSE", tradingsymbol=symbol, name=symbol, instrument_token=abs(hash(symbol)) % 99999,
        exchange_token=1, instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )


class _Master:
    def __init__(self, _db):
        pass

    async def get(self, exchange, tradingsymbol):
        return _instrument(tradingsymbol)


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


@pytest.mark.asyncio
async def test_quotes_are_returned_per_symbol(mongo, monkeypatch):
    class _Provider:
        async def quote(self, instrument):
            return {"last_price": 101.5}

    monkeypatch.setattr(marks, "InstrumentMaster", _Master)
    monkeypatch.setattr(marks, "YFinanceProvider", _Provider)

    assert await marks.mark_prices(mongo, ["RELIANCE", "TCS"]) == {
        "RELIANCE": 101.5,
        "TCS": 101.5,
    }


@pytest.mark.asyncio
async def test_a_failing_symbol_is_omitted_not_zeroed(mongo, monkeypatch):
    class _Provider:
        async def quote(self, instrument):
            if instrument.tradingsymbol == "TCS":
                raise RuntimeError("provider said no")
            return {"last_price": 101.5}

    monkeypatch.setattr(marks, "InstrumentMaster", _Master)
    monkeypatch.setattr(marks, "YFinanceProvider", _Provider)

    assert await marks.mark_prices(mongo, ["RELIANCE", "TCS"]) == {"RELIANCE": 101.5}


@pytest.mark.asyncio
async def test_a_hanging_provider_gives_up_rather_than_stalling(mongo, monkeypatch):
    class _Provider:
        async def quote(self, instrument):
            await asyncio.sleep(30)

    monkeypatch.setattr(marks, "InstrumentMaster", _Master)
    monkeypatch.setattr(marks, "YFinanceProvider", _Provider)
    monkeypatch.setattr(marks, "TIMEOUT_SECONDS", 0.05)

    assert await asyncio.wait_for(marks.mark_prices(mongo, ["RELIANCE"]), timeout=2) == {}


@pytest.mark.asyncio
async def test_no_symbols_makes_no_calls(mongo, monkeypatch):
    class _Provider:
        async def quote(self, instrument):
            raise AssertionError("should not be called")

    monkeypatch.setattr(marks, "InstrumentMaster", _Master)
    monkeypatch.setattr(marks, "YFinanceProvider", _Provider)

    assert await marks.mark_prices(mongo, []) == {}


class _Cache:
    """A quote cache holding RELIANCE at 100, `age` seconds old."""

    def __init__(self, age):
        self.quote = json.dumps({"ltp": 100.0, "at": time.time() - age})

    async def mget(self, keys):
        return [self.quote for _ in keys]


@pytest.mark.parametrize("phase, kwargs, expected", [
    ("closed", {}, 100.0),  # no session since the quote: it is still the price, no Yahoo call
    ("post", {}, 100.0),
    ("session", {}, 999.0),  # the market is moving: older than the default is re-fetched
    ("closed", {"max_age_seconds": 20}, 999.0),  # an order path's explicit limit always holds
])
@pytest.mark.asyncio
async def test_quote_age_limit_depends_on_the_session(mongo, monkeypatch, phase, kwargs, expected):
    class _Provider:
        async def quote(self, instrument):
            return {"last_price": 999.0}

    async def no_store(*_):
        return None

    monkeypatch.setattr(marks, "InstrumentMaster", _Master)
    monkeypatch.setattr(marks, "YFinanceProvider", _Provider)
    monkeypatch.setattr(marks, "_redis", lambda: _Cache(age=300))
    monkeypatch.setattr(marks, "store_quotes", no_store)
    monkeypatch.setattr(marks, "market_phase", lambda now: phase)

    assert await marks.mark_prices(mongo, ["RELIANCE"], **kwargs) == {"RELIANCE": expected}
