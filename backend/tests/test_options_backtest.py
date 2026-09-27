"""Options backtests: model-priced contracts stand in for a premium history
that does not exist, so an options strategy can face the backtest gate."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.components.shared.models import PriceCandle
from backend.data.providers.kite_provider import KiteProvider
from backend.engine.backtest import run_backtest
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.options.backtest import ModelOptions, _expiry, _strike_step
from backend.risk.backtest_gate import BacktestGateStore
from backend.risk.gate_backtest import backtest_for_gate
from backend.tests.test_intraday_options import _BuyCallOnce

START = datetime(2024, 12, 2, 4, 0, tzinfo=timezone.utc)  # 09:30 IST, a Monday


def _bar(close, i=0):
    return SimpleNamespace(close=close, timestamp=START + timedelta(minutes=5 * i))


def test_strike_steps_and_monthly_expiry():
    assert [_strike_step(s) for s in (95.0, 1300.0, 2905.0, 24_800.0)] == [1.0, 20.0, 50.0, 250.0]
    assert str(_expiry(datetime(2024, 12, 2).date())) == "2024-12-26"
    assert str(_expiry(datetime(2024, 12, 26).date())) == "2025-01-30"  # expiry day itself rolls


async def test_contracts_sit_around_spot_and_calls_gain_with_the_underlying():
    model = ModelOptions({"RELIANCE": 500})
    for i, close in enumerate([1300.0, 1302.0, 1298.0, 1301.0] * 10):
        model.observe("RELIANCE", _bar(close, i))

    calls = await model.option_contracts("RELIANCE", "CE")
    assert len(calls) == 11 and {c.lot_size for c in calls} == {500}
    atm = min(calls, key=lambda c: abs(c.strike - 1301.0))
    assert atm.strike == 1300.0 and atm.tradingsymbol == "RELIANCE24DEC1300CE"
    before = await model(atm)
    model.observe("RELIANCE", _bar(1330.0, 41))
    assert 0 < before < await model(atm)
    assert await model.option_contracts("TCS", "CE") == []  # no lot size, no contracts


class _Provider:
    def __init__(self, closes):
        self.closes = closes

    async def history(self, instrument, interval, period):
        return [PriceCandle(symbol=instrument.tradingsymbol, timestamp=START + timedelta(minutes=5 * i),
                            open=c, high=c, low=c, close=c, volume=1000.0)
                for i, c in enumerate(self.closes)]


def _underlying(symbol="RELIANCE", token=1):
    return Instrument(exchange="NSE", tradingsymbol=symbol, name=symbol, instrument_token=token,
                      exchange_token=token, instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)


async def test_run_backtest_trades_options_on_model_premiums():
    result = await run_backtest(
        [_BuyCallOnce()], _Provider([100.0] * 20 + [104.0, 111.0, 111.0]), [_underlying()],
        start=START - timedelta(days=1), end=START + timedelta(days=1), timeframe="5m",
        model_options=ModelOptions({"RELIANCE": 250}),
    )
    buy, sell = result.trades
    assert buy["symbol"] == sell["symbol"] == "RELIANCE24DEC100CE"
    assert sell["realized_pnl"] > 0  # the underlying ran from 100 to 111 past the target


async def test_kite_history_fetches_a_year_of_5m_candles_in_windows():
    kite = MagicMock()
    kite.historical_data.return_value = []
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)
    provider = KiteProvider(kite_client_factory=lambda: kite, now_fn=lambda: now)
    with patch("backend.data.providers.kite_provider.asyncio.to_thread",
               new=AsyncMock(side_effect=lambda fn, *a: fn(*a))):
        await provider.history(_underlying(), interval="5m", period="max")
    spans = [(c.args[1], c.args[2]) for c in kite.historical_data.call_args_list]
    assert len(spans) == 4 and spans[0][0] == now - timedelta(days=365) and spans[-1][1] == now
    assert all(end - start <= timedelta(days=99) for start, end in spans)


async def test_gate_backtest_records_the_options_strategy():
    db = AsyncMongoMockClient()["test_db"]
    master = InstrumentMaster(db)
    await master.upsert_many([
        _underlying(),
        Instrument(exchange="NFO", tradingsymbol="RELIANCE24DEC1300CE", name="RELIANCE", instrument_token=9,
                   exchange_token=9, instrument_type="CE", segment="NFO-OPT", lot_size=500, tick_size=0.05,
                   expiry=datetime(2030, 12, 26), strike=1300.0),
    ])
    result = await backtest_for_gate(db, "orb_options", _Provider([1300.0] * 30), START + timedelta(days=1))
    assert result.symbol == "RELIANCE"
    doc = await BacktestGateStore(db).latest("orb_options")
    assert doc is not None and doc["passed"] is False  # no trades, a day of data


async def test_gate_backtest_of_options_needs_synced_contracts():
    db = AsyncMongoMockClient()["test_db"]
    await InstrumentMaster(db).upsert_many([_underlying()])
    with pytest.raises(ValueError, match="connect Kite"):
        await backtest_for_gate(db, "orb_options", _Provider([]), START)
