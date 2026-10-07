import random
from datetime import datetime, timedelta

import pandas as pd

from backend.components.quant.indicators import Indicators
from backend.core.models import Bar
from backend.engine.session import IST
from backend.strategies.blocks.state import SymbolState


def _bars(days=2, per_day=60, seed=7):
    rnd, px, out = random.Random(seed), 100.0, []
    for d in range(days):
        t0 = datetime(2026, 10, 5 + d, 9, 15, tzinfo=IST)
        for i in range(per_day):
            o = px
            px = max(1.0, px + rnd.uniform(-1, 1))
            hi, lo = max(o, px) + rnd.random(), min(o, px) - rnd.random()
            out.append(Bar(instrument_token=1, timeframe="5m", timestamp=(t0 + timedelta(minutes=5 * i)).astimezone(),
                           open=o, high=hi, low=lo, close=px, volume=rnd.randint(100, 1000)))
    return out


def test_vwap_atr_ema_rsi_match_the_batch_indicators():
    bars = _bars()
    st = SymbolState({9, 20}, {14}, {15})
    for b in bars:
        st.update(b)
    df = pd.DataFrame([b.model_dump() for b in bars])
    session = df["timestamp"].dt.tz_convert(IST).dt.date
    c = df["close"]
    assert abs(st.vwap - Indicators.vwap(df["high"], df["low"], c, df["volume"], session).iloc[-1]) < 1e-6
    assert abs(st.atr - Indicators.atr(df["high"], df["low"], c).iloc[-1]) < 1e-6
    assert abs(st.ema(9) - Indicators.ema(c, 9).iloc[-1]) < 1e-6
    assert abs(st.ema(20) - Indicators.ema(c, 20).iloc[-1]) < 1e-6
    r = Indicators.rsi(c, 14)
    assert abs(st.rsi(14) - r.iloc[-1]) < 1e-6
    assert abs(st.prev_rsi(14) - r.iloc[-2]) < 1e-6
    assert st.vol_avg20 == df["volume"].iloc[-21:-1].mean()
    assert st.prev_bar == bars[-2] and st.last_bar == bars[-1]


def test_new_session_resets_vwap_and_range_and_sets_prev_close():
    bars = _bars()
    st = SymbolState(set(), set(), {15})
    for b in bars[:60]:
        st.update(b)
    assert st.range_high(15) == max(b.high for b in bars[:3])
    assert st.range_low(15) == min(b.low for b in bars[:3])
    st.update(bars[60])
    assert st.prev_close == bars[59].close
    assert st.bars_today == 1 and st.open == bars[60].open
    assert st.vwap == (bars[60].high + bars[60].low + bars[60].close) / 3
    assert st.range_high(15) is None
    st.update(bars[61])
    assert st.range_high(15) is None
    st.update(bars[62])
    assert st.range_high(15) == max(b.high for b in bars[60:63])


def test_explicit_prev_close_wins():
    bars = _bars()
    st = SymbolState(set(), set(), set())
    for b in bars[:60]:
        st.update(b)
    st.update(bars[60], prev_close=101.5)
    assert st.prev_close == 101.5
