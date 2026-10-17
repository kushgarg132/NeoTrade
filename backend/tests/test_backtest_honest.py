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


@pytest.mark.asyncio
async def test_backtest_trail_never_falls_when_atr_widens():
    flat = (100, 102.5, 97.5, 100)
    # Bar 17's close of 120 lifts the trail to 120 - 2 x 85/14 ~ 107.86. Bar 18 is wide (TR 32): recomputed,
    # the trail would fall to 121 - 2 x 8 = 105. Bar 19's low of 106 must still hit the kept 107.86.
    kept = 120 - 2 * (13 * 5 + 20) / 14
    rows = [flat] * 17 + [(100, 120, 100, 120), (120, 140, 108, 121), (115, 116, 106, 110), flat]
    sell = (await _run_daily(_SwingBuy(15, 20, 2.0), rows)).trades[1]
    assert sell["price"] == pytest.approx(kept * 0.999)
    assert sell["timestamp"] == (T0 + timedelta(days=19)).isoformat()


@pytest.mark.asyncio
async def test_a_gap_through_the_stop_fills_at_the_open():
    flat = (100, 102.5, 97.5, 100)
    swing = await _run_daily(_SwingBuy(0, 20, None), [flat, flat, (40, 45, 35, 42), flat])
    assert swing.trades[1]["price"] == pytest.approx(40 * 0.999)  # opened under the stop of 50
    intraday = await _run([(100, 101, 99, 100), (102, 103, 101, 102), (90, 92, 88, 90)],
                          account_size=25_000.0, max_exposure=15_000.0, per_trade_cap=5_000.0)
    assert intraday.trades[1]["price"] == pytest.approx(90 * 0.999)  # the open too: no fill at a level never traded


class _BuyTwice:
    """Buys on bars 0 and 3, a 95 stop each time."""

    def __init__(self):
        self.spec = StrategySpec(name="buy-twice", mode="INTRADAY", timeframe="5m", warmup_bars=0, universe=["ITC"])
        self.seen = 0

    def on_start(self, ctx): ...
    def on_fill(self, ctx, fill): ...

    def on_bar(self, ctx, bar):
        if self.seen in (0, 3):
            ctx.submit(Intent(symbol="ITC", side=Side.BUY, strength=1.0, reason_codes=["t"], stop_hint=95.0))
        self.seen += 1


@pytest.mark.asyncio
async def test_a_second_round_trip_does_not_erase_the_first():
    instrument = Instrument(exchange="NSE", tradingsymbol="ITC", name="ITC", instrument_token=1, exchange_token=1,
                            instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)
    flat, stop = (100, 101, 99, 100), (100, 100, 94, 95)
    candles = _candles([flat, flat, stop, flat, flat, stop, flat])
    result = await run_backtest([_BuyTwice()], _Provider(candles), [instrument], candles[0].timestamp,
                                candles[-1].timestamp, "5m", account_size=25_000.0, max_exposure=15_000.0,
                                per_trade_cap=5_000.0)
    assert result.total_trades == 2
    assert all(t["gross_pnl"] <= 0 for t in result.trades)  # two losers, no phantom win on the re-entry


@pytest.mark.asyncio
async def test_the_entry_bar_itself_can_stop_the_trade_out():
    # Filled at bar 1's open (102), bar 1 then trades down to 94: stopped at 95 there,
    # not carried to a later bar that never revisits the stop.
    result = await _run([(100, 101, 99, 100), (102, 103, 94, 101), (101, 110, 100, 108)],
                        account_size=25_000.0, max_exposure=15_000.0, per_trade_cap=5_000.0)
    sell = result.trades[1]
    assert sell["price"] == pytest.approx(95 * 0.999)
    assert sell["timestamp"] == (T0 + timedelta(minutes=5)).isoformat()


@pytest.mark.asyncio
async def test_square_off_closes_once_and_never_opens_the_other_side():
    # 09:30..15:25 IST, then the next session from 09:15. The square-off used to
    # fire again on the bar its first order filled, opening a short at 15:25.
    times = ([T0 + timedelta(minutes=5 * i) for i in range(72)]
             + [T0 + timedelta(days=1, minutes=-15 + 5 * i) for i in range(10)])
    candles = [PriceCandle(symbol="ITC", timestamp=t, open=100, high=101, low=99, close=100, volume=1000)
               for t in times]
    instrument = Instrument(exchange="NSE", tradingsymbol="ITC", name="ITC", instrument_token=1, exchange_token=1,
                            instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)
    result = await run_backtest([_BuyOnce()], _Provider(candles), [instrument], candles[0].timestamp,
                                candles[-1].timestamp, "5m", account_size=25_000.0, max_exposure=15_000.0,
                                per_trade_cap=5_000.0)
    assert [t["side"] for t in result.trades] == ["BUY", "SELL"]
    assert result.total_trades == 1


class _LongTermSell:
    def __init__(self):
        self.spec = StrategySpec(name="lt-sell", mode="LONGTERM", timeframe="1d", warmup_bars=0, universe=["ITC"])

    def on_start(self, ctx): ...
    def on_fill(self, ctx, fill): ...

    def on_bar(self, ctx, bar):
        ctx.submit(Intent(symbol="ITC", side=Side.SELL, strength=1.0, reason_codes=["t"], stop_hint=110.0,
                          target_hint=80.0))


@pytest.mark.asyncio
async def test_a_long_term_sell_with_nothing_held_is_not_a_short():
    flat = (100, 102.5, 97.5, 100)
    result = await _run_daily(_LongTermSell(), [flat, flat, (90, 91, 79, 80), flat])
    assert result.trades == []


@pytest.mark.asyncio
async def test_profit_factor_is_over_round_trips():
    # One winner (entry 102, out at the 130 target) and one stopped loser.
    instrument = Instrument(exchange="NSE", tradingsymbol="ITC", name="ITC", instrument_token=1, exchange_token=1,
                            instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)

    class _TwoTrades(_BuyTwice):
        def on_bar(self, ctx, bar):
            if self.seen in (0, 3):
                ctx.submit(Intent(symbol="ITC", side=Side.BUY, strength=1.0, reason_codes=["t"], stop_hint=95.0,
                                  target_hint=130.0))
            self.seen += 1

    flat = (100, 101, 99, 100)
    candles = _candles([flat, flat, (110, 131, 109, 125), flat, flat, (100, 100, 94, 95), flat])
    result = await run_backtest([_TwoTrades()], _Provider(candles), [instrument], candles[0].timestamp,
                                candles[-1].timestamp, "5m", account_size=25_000.0, max_exposure=15_000.0,
                                per_trade_cap=5_000.0)
    buy1, sell1, buy2, sell2 = result.trades
    win = sell1["gross_pnl"] - buy1["costs"] - sell1["costs"]
    loss = -(sell2["gross_pnl"] - buy2["costs"] - sell2["costs"])
    assert result.profit_factor == pytest.approx(win / loss)
