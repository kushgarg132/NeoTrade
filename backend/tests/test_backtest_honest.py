"""The backtest tests what is traded: the account's size and per-trade cap,
next-bar fills, stops/targets hit inside a bar, and round trips counted as
trades. It used to size a Rs 10 lakh account with no cap, fill at the signal
bar's close, never exit intraday positions at their levels, and count every
fill as a trade."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.components.shared.models import PriceCandle
from backend.core.models import Intent, Side
from backend.engine.backtest import run_backtest
from backend.engine.protocols import StrategySpec
from backend.instruments.models import Instrument

T0 = datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc)  # 09:30 IST


class _BuyOnce:
    def __init__(self):
        self.spec = StrategySpec(name="buy-once", mode="INTRADAY", timeframe="5m", warmup_bars=0, universe=["ITC"])
        self.fired = False

    def on_start(self, ctx): ...
    def on_fill(self, ctx, fill): ...

    def on_bar(self, ctx, bar):
        if not self.fired:
            self.fired = True
            ctx.submit(Intent(symbol="ITC", side=Side.BUY, strength=1.0, reason_codes=["t"],
                              stop_hint=95.0, target_hint=130.0))


class _Provider:
    def __init__(self, bars):
        self.bars = bars

    async def history(self, instrument, interval, period=None, start=None, end=None):
        return self.bars

    async def quote(self, instrument):
        return {}


def _candles(rows):
    return [PriceCandle(symbol="ITC", timestamp=T0 + timedelta(minutes=5 * i), open=o, high=h, low=l, close=c, volume=1000)
            for i, (o, h, l, c) in enumerate(rows)]


async def _run(rows, **account):
    instrument = Instrument(exchange="NSE", tradingsymbol="ITC", name="ITC", instrument_token=1, exchange_token=1,
                            instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)
    candles = _candles(rows)
    return await run_backtest([_BuyOnce()], _Provider(candles), [instrument], candles[0].timestamp,
                              candles[-1].timestamp, "5m", **account)


@pytest.mark.asyncio
async def test_fills_next_open_and_exits_at_the_stop_inside_a_bar():
    result = await _run([(100, 101, 99, 100), (102, 103, 101, 102), (101, 101, 94, 96), (96, 97, 95, 96)],
                        account_size=25_000.0, max_exposure=15_000.0, per_trade_cap=5_000.0)
    buy, sell = result.trades[0], result.trades[1]
    assert buy["price"] == pytest.approx(102 * 1.001)       # next bar's open + 10 bps
    assert sell["price"] == pytest.approx(95 * 0.999)       # the stop level, inside bar 3
    assert buy["quantity"] * 102 <= 5_000                    # per-trade cap honoured
    assert result.total_trades == 1                         # one round trip, not two fills


@pytest.mark.asyncio
async def test_target_exit_and_stop_wins_when_both_cross():
    target = await _run([(100, 101, 99, 100), (102, 103, 101, 102), (110, 131, 109, 125)],
                        account_size=25_000.0, max_exposure=15_000.0, per_trade_cap=5_000.0)
    assert target.trades[1]["price"] == pytest.approx(130 * 0.999)
    both = await _run([(100, 101, 99, 100), (102, 103, 101, 102), (100, 131, 94, 100)],
                      account_size=25_000.0, max_exposure=15_000.0, per_trade_cap=5_000.0)
    assert both.trades[1]["price"] == pytest.approx(95 * 0.999)  # conservative: the stop


@pytest.mark.asyncio
async def test_gate_backtests_use_the_admins_account_settings():
    from mongomock_motor import AsyncMongoMockClient

    from backend.prefs import PrefsStore
    from backend.risk.gate_backtest import backtest_account

    db = AsyncMongoMockClient()["test_db"]
    assert (await backtest_account(db))["per_trade_cap"] > 0  # defaults when there is no admin
    await db["users"].insert_one({"id": "owner", "role": "admin"})
    await PrefsStore(db).update("owner", {"account_size": 25_000.0, "max_exposure": 15_000.0, "per_trade_cap": 5_000.0})
    assert await backtest_account(db) == {"account_size": 25_000.0, "max_exposure": 15_000.0, "per_trade_cap": 5_000.0}


class _SwingBuy:
    """Buys once on bar `at`, daily, with a swing intent's exits."""

    def __init__(self, at, hold, trail):
        self.spec = StrategySpec(name="swing", mode="LONGTERM", timeframe="1d", warmup_bars=0, universe=["ITC"])
        self.at, self.hold, self.trail, self.seen = at, hold, trail, 0

    def on_start(self, ctx): ...
    def on_fill(self, ctx, fill): ...

    def on_bar(self, ctx, bar):
        if self.seen == self.at:
            ctx.submit(Intent(symbol="ITC", side=Side.BUY, strength=1.0, reason_codes=["t"], stop_hint=50.0,
                              target_hint=500.0, max_hold_days=self.hold, trail_atr=self.trail))
        self.seen += 1


async def _run_daily(strategy, rows):
    instrument = Instrument(exchange="NSE", tradingsymbol="ITC", name="ITC", instrument_token=1, exchange_token=1,
                            instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)
    candles = [PriceCandle(symbol="ITC", timestamp=T0 + timedelta(days=i), open=o, high=h, low=l, close=c, volume=1000)
               for i, (o, h, l, c) in enumerate(rows)]
    return await run_backtest([strategy], _Provider(candles), [instrument], candles[0].timestamp, candles[-1].timestamp,
                              "1d", account_size=25_000.0, max_exposure=15_000.0, per_trade_cap=5_000.0)


@pytest.mark.asyncio
async def test_backtest_applies_max_hold_and_trail():
    flat = (100, 102.5, 97.5, 100)
    # Max hold 3: signal bar 0, entry at bar 1's open, out at the close of bar 4 (3 bars after entry).
    held = await _run_daily(_SwingBuy(0, 3, None), [flat, flat, (100, 102, 98, 101), (100, 102, 98, 102),
                                                    (100, 104, 98, 103), (100, 105, 98, 104)])
    sell = held.trades[1]
    assert sell["price"] == pytest.approx(103 * 0.999)
    assert sell["timestamp"] == (T0 + timedelta(days=4)).isoformat()

    # Trail 2 x ATR: 16 flat bars (true range 5), signal on bar 15, entry bar 16. Bar 17 closes 120 (TR 20)
    # without touching the entry-day trail of 90; bar 18 trades through 120 - 2 x ATR and exits there.
    trail = 120 - 2 * (13 * 5 + 20) / 14
    rows = [flat] * 17 + [(100, 120, 100, 120), (118, 119, 100, 105), flat]
    trailed = await _run_daily(_SwingBuy(15, 20, 2.0), rows)
    sell = trailed.trades[1]
    assert sell["price"] == pytest.approx(trail * 0.999)
    assert sell["timestamp"] == (T0 + timedelta(days=18)).isoformat()
