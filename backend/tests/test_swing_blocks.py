import random
from datetime import datetime, timedelta

import pandas as pd

from backend.components.quant.indicators import Indicators
from backend.core.models import Bar
from backend.engine.session import IST
from backend.strategies.blocks import vocab
from backend.strategies.blocks.swing import filter_passes, setup_fires
from backend.strategies.blocks.swing_state import SwingState


def _bar(i, o, h, l, c, v=1000.0):
    ts = datetime(2025, 1, 1, 15, 30, tzinfo=IST) + timedelta(days=i)
    return Bar(instrument_token=1, timeframe="1d", timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def _flat(n, px=100.0, v=1000.0):
    return [_bar(i, px, px + 1, px - 1, px, v) for i in range(n)]


def _state(bars):
    s = SwingState()
    for b in bars:
        s.update(b)
    return s


def test_swing_state_matches_batch_indicators():
    rnd, px, bars = random.Random(3), 100.0, []
    for i in range(300):
        o, px = px, max(1.0, px + rnd.uniform(-2, 2))
        bars.append(_bar(i, o, max(o, px) + rnd.random(), min(o, px) - rnd.random(), px, rnd.randint(100, 900)))
    df = pd.DataFrame([b.model_dump() for b in bars])
    s, last = _state(bars), len(bars) - 1
    assert abs(s.sma(50) - Indicators.sma(df.close, 50).iloc[last]) < 1e-9
    assert abs(s.sma(200) - Indicators.sma(df.close, 200).iloc[last]) < 1e-9
    assert abs(s.atr - Indicators.atr(df.high, df.low, df.close).iloc[last]) < 1e-9
    assert abs(s.rsi2 - Indicators.rsi(df.close, 2).iloc[last]) < 1e-9
    assert abs(s.high_n(20) - df.high.iloc[last - 20:last].max()) < 1e-12
    assert abs(s.ret(63) - (df.close.iloc[last] / df.close.iloc[last - 63] - 1)) < 1e-12


def test_missing_history_is_silent():
    s = _state(_flat(10))
    assert not setup_fires("breakout_n", {"days": 20}, s, None)
    assert not setup_fires("rsi2_dip", {"level": 10}, s, None)
    assert not filter_passes("trend_ma", {"period": "50"}, s, None, None)
    assert not filter_passes("liquidity", {"min_cr": 1}, s, None, None)


def test_breakout_n():
    bars = _flat(30)
    assert not setup_fires("breakout_n", {"days": 20}, _state(bars), None)
    bars.append(_bar(30, 100, 103, 100, 102))
    assert setup_fires("breakout_n", {"days": 20}, _state(bars), None)


def test_pullback_ma():
    bars = [_bar(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(60)]  # steady uptrend
    p = {"trend": "50", "pull": "10"}
    quiet = _state(bars + [_bar(60, 160, 161, 158, 159)])
    assert not setup_fires("pullback_ma", p, quiet, None)
    dip = _bar(60, 150, 151, 120, 140)  # low under the 10-day average
    up = _bar(61, 141, 160, 140, 155)  # closes above the dip bar's high, still above the 50-day
    assert setup_fires("pullback_ma", p, _state(bars + [dip, up]), None)


def test_rsi2_dip():
    bars = [_bar(i, 100 + i * .1, 101 + i * .1, 99 + i * .1, 100 + i * .1) for i in range(210)]
    assert not setup_fires("rsi2_dip", {"level": 10}, _state(bars), None)
    px = bars[-1].close
    bars += [_bar(210 + k, px - k, px - k + 1, px - k - 1, px - k - 1) for k in range(3)]
    s = _state(bars)
    assert s.rsi2 < 10 and s.close > s.sma(200)
    assert setup_fires("rsi2_dip", {"level": 10}, s, None)
    assert not setup_fires("rsi2_dip", {"level": 2}, _state(bars[:-1] + [_bar(212, 100, 101, 99, 100)]), None)


def test_gap_hold():
    base = _flat(5)
    assert setup_fires("gap_hold", {"min_pct": 2.0}, _state(base + [_bar(5, 103, 105, 103, 104)]), None)
    assert not setup_fires("gap_hold", {"min_pct": 2.0}, _state(base + [_bar(5, 103, 105, 101, 102)]), None)
    assert not setup_fires("gap_hold", {"min_pct": 5.0}, _state(base + [_bar(5, 103, 105, 103, 104)]), None)


def test_momentum_rank():
    s = _state(_flat(5))
    assert setup_fires("momentum_rank", {"lookback": "63", "top_pct": 10}, s, 8.0)
    assert not setup_fires("momentum_rank", {"lookback": "63", "top_pct": 10}, s, 12.0)
    assert not setup_fires("momentum_rank", {"lookback": "63", "top_pct": 10}, s, None)


def test_volume_breakout():
    base = _flat(25)
    p = {"multiple": 2.0}
    assert setup_fires("volume_breakout", p, _state(base + [_bar(25, 100, 110, 100, 109, 3000)]), None)
    assert not setup_fires("volume_breakout", p, _state(base + [_bar(25, 100, 110, 100, 105, 3000)]), None)  # weak close
    assert not setup_fires("volume_breakout", p, _state(base + [_bar(25, 100, 110, 100, 109, 1500)]), None)


def test_filters():
    s = _state(_flat(60, v=2_000_000))  # turnover 2e8 = Rs 20 crore, ATR 2%
    assert not filter_passes("trend_ma", {"period": "50"}, s, None, None)  # flat: close == average
    s.update(_bar(60, 100, 102, 100, 101, 2_000_000))
    assert filter_passes("trend_ma", {"period": "50"}, s, None, None)
    assert filter_passes("regime_is", {"regimes": ["risk_on"]}, s, "risk_on", None)
    assert not filter_passes("regime_is", {"regimes": ["risk_on"]}, s, None, None)
    assert filter_passes("sector_rs", {"min": 1.0}, s, None, 1.5)
    assert not filter_passes("sector_rs", {"min": 1.0}, s, None, None)
    assert filter_passes("atr_pct", {"min": 1.0, "max": 3.0}, s, None, None)
    assert not filter_passes("atr_pct", {"min": 2.5, "max": 3.0}, s, None, None)
    assert filter_passes("liquidity", {"min_cr": 20}, s, None, None)
    assert not filter_passes("liquidity", {"min_cr": 21}, s, None, None)


def test_vocab_shapes():
    assert vocab.SWING_EXITS["stop"]["swing_low"] == ()
    assert vocab.SWING_SETUPS["pullback_ma"]["trend"] == ("50", "100", "200")
    assert set(vocab.SWING_FILTERS) == {"trend_ma", "regime_is", "sector_rs", "atr_pct", "liquidity"}
