"""Live option premiums from the user's own broker: Kite quotes the NFO
contract directly; Upstox reads the strike off its option chain (one chain
call per underlying and expiry); Kite is preferred when both are live."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.brokers.protocol import BrokerSessionState
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.options import premiums


def _contract(strike=2760.0, kind="PE"):
    return Instrument(exchange="NFO", tradingsymbol=f"RELIANCE26OCT{int(strike)}{kind}", name="RELIANCE",
                      instrument_token=int(strike), exchange_token=int(strike), instrument_type=kind,
                      segment="NFO-OPT", lot_size=250, tick_size=0.05, expiry=datetime(2026, 10, 27), strike=strike)


class _Kite:
    def __init__(self, state=BrokerSessionState.ACTIVE):
        self._state = state
        self.quote = AsyncMock(return_value={"last_price": 41.35})

    async def state(self):
        return self._state


class _Upstox:
    def __init__(self, state=BrokerSessionState.ACTIVE):
        self._state = state
        self.option_chain = AsyncMock(return_value=[
            {"strike": 2760.0, "call": {"ltp": 180.0}, "put": {"ltp": 39.9}},
            {"strike": 2780.0, "call": {"ltp": 165.0}, "put": {"ltp": 47.5}},
        ])
        self._resolve = AsyncMock(return_value={"instrument_key": "NSE_EQ|INE002A01018"})

    async def state(self):
        return self._state


@pytest.fixture
async def db():
    db = AsyncMongoMockClient()["test_db"]
    await InstrumentMaster(db).upsert_many([Instrument(
        exchange="NSE", tradingsymbol="RELIANCE", name="RELIANCE", instrument_token=1, exchange_token=1,
        instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )])
    return db


@pytest.mark.asyncio
async def test_kite_quotes_the_contract_directly():
    kite = _Kite()
    assert await premiums._kite_source(kite)(_contract()) == 41.35
    kite.quote.assert_awaited_once()


@pytest.mark.asyncio
async def test_upstox_reads_the_strike_off_one_chain_per_expiry(db):
    upstox = _Upstox()
    source = premiums._upstox_source(upstox, InstrumentMaster(db))

    assert await source(_contract(2760.0)) == 39.9
    assert await source(_contract(2780.0)) == 47.5
    assert await source(_contract(2760.0, "CE")) == 180.0
    assert await source(_contract(9999.0)) is None  # strike not listed
    upstox.option_chain.assert_awaited_once_with("NSE_EQ|INE002A01018", "2026-10-27")


@pytest.mark.asyncio
async def test_a_broker_error_prices_nothing_rather_than_raising():
    kite = _Kite()
    kite.quote = AsyncMock(side_effect=RuntimeError("token expired"))
    assert await premiums._kite_source(kite)(_contract()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kite_state,upstox_state,expected", [
    (BrokerSessionState.ACTIVE, BrokerSessionState.ACTIVE, 41.35),   # Kite preferred
    (BrokerSessionState.NEEDS_LOGIN, BrokerSessionState.ACTIVE, 39.9),
    (BrokerSessionState.NEEDS_LOGIN, BrokerSessionState.NEEDS_LOGIN, None),
])
async def test_live_source_takes_the_first_connected_broker(db, monkeypatch, kite_state, upstox_state, expected):
    adapters = {"kite": _Kite(kite_state), "upstox": _Upstox(upstox_state)}
    monkeypatch.setattr(premiums, "get_broker_adapter", AsyncMock(side_effect=lambda b, *a: adapters[b]))

    source = await premiums.live_premium_source(db, "alice", None, None)

    if expected is None:
        assert source is None
    else:
        assert await source(_contract()) == expected
