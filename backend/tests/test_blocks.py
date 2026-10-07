from datetime import datetime, time, timedelta

from backend.core.models import Bar
from backend.engine.session import IST
from backend.strategies.blocks.blocks import filter_passes, setup_fires
from backend.strategies.blocks.state import SymbolState


def bar(i, o, h, l, c, v=1000, day=(2026, 10, 5)):
    ts = datetime(*day, 9, 15, tzinfo=IST) + timedelta(minutes=5 * i)
    return Bar(instrument_token=1, timeframe="5m", timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def feed(bars, ema=(), rsi=(), rng=(), prev_close=None):
    s = SymbolState(set(ema), set(rsi), set(rng))
    for i, b in enumerate(bars):
        s.update(b, prev_close if i == 0 else None)
    return s


def flat(n, price=100.0):
    return [bar(i, price, price + 0.5, price - 0.5, price) for i in range(n)]


def test_orb_break_long_and_quiet():
    base = [bar(0, 100, 101, 99, 100), bar(1, 100, 101, 99.5, 100.5), bar(2, 100.5, 101, 100, 100.8)]
    assert setup_fires("orb_break", {"range_minutes": 10}, feed(base + [bar(3, 100.8, 102, 100.8, 101.8)], rng=[10]), "long")
    assert not setup_fires("orb_break", {"range_minutes": 10}, feed(base + [bar(3, 100.8, 101, 100.5, 100.9)], rng=[10]), "long")
    assert not setup_fires("orb_break", {"range_minutes": 10}, feed(base + [bar(3, 100.8, 102, 100.8, 101.8)], rng=[10]), "short")


def test_orb_break_short():
    base = [bar(0, 100, 101, 99, 100), bar(1, 100, 101, 99.5, 100.5), bar(2, 100.5, 101, 100, 100.2)]
    assert setup_fires("orb_break", {"range_minutes": 10}, feed(base + [bar(3, 100, 100, 98, 98.5)], rng=[10]), "short")


def test_gap_up_down_and_quiet():
    up = feed([bar(0, 102, 103, 101, 102)], prev_close=100.0)
    assert setup_fires("gap", {"direction": "up", "min_pct": 1.0}, up, "long")
    assert not setup_fires("gap", {"direction": "down", "min_pct": 1.0}, up, "long")
    assert not setup_fires("gap", {"direction": "up", "min_pct": 3.0}, up, "long")
    down = feed([bar(0, 98, 99, 97, 98), bar(1, 98, 99, 97, 98)], prev_close=100.0)
    assert setup_fires("gap", {"direction": "down", "min_pct": 1.0}, down, "short")


def test_gap_is_silent_without_a_previous_close():
    s = feed([bar(0, 102, 103, 101, 102)])
    assert setup_fires("gap", {"direction": "up", "min_pct": 1.0}, s, "long") is False


def test_vwap_cross_reclaim_and_lose():
    below = [bar(0, 100, 100.5, 99.5, 100), bar(1, 100, 100, 98, 98.5)]
    assert setup_fires("vwap_cross", {"mode": "reclaim"}, feed(below + [bar(2, 98.5, 102, 98.5, 101)]), "long")
    assert not setup_fires("vwap_cross", {"mode": "reclaim"}, feed(below + [bar(2, 98.5, 99, 98, 98.6)]), "long")
    above = [bar(0, 100, 100.5, 99.5, 100), bar(1, 100, 102, 100, 101.5)]
    assert setup_fires("vwap_cross", {"mode": "lose"}, feed(above + [bar(2, 101, 101, 97, 98)]), "short")


def test_rsi_cross_up_down_and_quiet():
    falling = [bar(i, 100 - i, 100 - i, 99 - i, 99 - i) for i in range(6)]
    s = feed(falling + [bar(6, 94, 99, 94, 99)], rsi=[3])
    lo, hi = s.prev_rsi(3), s.rsi(3)
    assert lo < hi
    level = int((lo + hi) / 2)
    assert setup_fires("rsi_cross", {"period": 3, "level": level, "direction": "up"}, s, "long")
    assert not setup_fires("rsi_cross", {"period": 3, "level": level, "direction": "down"}, s, "long")
    assert not setup_fires("rsi_cross", {"period": 3, "level": 99, "direction": "up"}, s, "long")
    peak = feed([bar(i, 100 + i, 101 + i, 100 + i, 101 + i) for i in range(6)] + [bar(6, 106, 106, 99, 99)], rsi=[3])
    lvl = int((peak.prev_rsi(3) + peak.rsi(3)) / 2)
    assert setup_fires("rsi_cross", {"period": 3, "level": lvl, "direction": "down"}, peak, "short")


def test_ema_pullback_long_short_quiet():
    run = [bar(i, 100 + i, 101 + i, 100 + i, 101 + i) for i in range(5)]
    touch = bar(5, 104, 104.5, 100.5, 104)  # dips to the EMA
    s = feed(run + [touch, bar(6, 104, 106, 104, 105.5)], ema=[3])
    assert setup_fires("ema_pullback", {"period": 3}, s, "long")
    assert not setup_fires("ema_pullback", {"period": 3}, s, "short")
    quiet = feed(run + [touch, bar(6, 104, 104.4, 103.5, 104.2)], ema=[3])
    assert not setup_fires("ema_pullback", {"period": 3}, quiet, "long")
    dn = [bar(i, 120 - i, 120 - i, 119 - i, 119 - i) for i in range(5)]
    bounce = bar(5, 116, 120, 115.5, 116)
    s2 = feed(dn + [bounce, bar(6, 116, 116, 113, 114)], ema=[3])
    assert setup_fires("ema_pullback", {"period": 3}, s2, "short")


def test_volume_spike_fires_and_quiet():
    base = flat(20)
    assert setup_fires("volume_spike", {"multiple": 2.0}, feed(base + [bar(20, 100, 101, 99, 100, v=3000)]), "long")
    assert not setup_fires("volume_spike", {"multiple": 2.0}, feed(base + [bar(20, 100, 101, 99, 100, v=1500)]), "long")
    assert not setup_fires("volume_spike", {"multiple": 2.0}, feed(flat(5)), "long")  # warm-up


def test_filters_without_data_refuse():
    s = feed(flat(2))
    assert filter_passes("regime_is", {"regimes": ["risk_on"]}, s, None, None, time(10, 0)) is False
    assert filter_passes("sector_rs", {"min": 0.0}, s, "risk_on", None, time(10, 0)) is False
    assert filter_passes("atr_pct", {"min": 0.3, "max": 3.0}, s, None, None, time(10, 0)) is False


def test_regime_sector_time():
    s = feed(flat(2))
    t = time(10, 0)
    assert filter_passes("regime_is", {"regimes": ["risk_on", "neutral"]}, s, "neutral", None, t)
    assert not filter_passes("regime_is", {"regimes": ["risk_on"]}, s, "risk_off", None, t)
    assert filter_passes("sector_rs", {"min": 0.5}, s, None, 0.5, t)
    assert not filter_passes("sector_rs", {"min": 0.5}, s, None, 0.4, t)
    w = {"start": "09:30", "end": "14:45"}
    assert filter_passes("time_window", w, s, None, None, time(9, 30))
    assert not filter_passes("time_window", w, s, None, None, time(14, 45))
    assert not filter_passes("time_window", w, s, None, None, time(9, 29))


def test_atr_pct_vwap_volume_confirm():
    s = feed(flat(21))  # atr 1.0 on close 100 -> 1%
    t = time(10, 0)
    assert filter_passes("atr_pct", {"min": 0.5, "max": 2.0}, s, None, None, t)
    assert not filter_passes("atr_pct", {"min": 1.5, "max": 3.0}, s, None, None, t)
    up = feed(flat(3) + [bar(3, 100, 103, 100, 103)])
    assert filter_passes("price_vs_vwap", {"side": "above"}, up, None, None, t)
    assert not filter_passes("price_vs_vwap", {"side": "below"}, up, None, None, t)
    vol = feed(flat(20) + [bar(20, 100, 101, 99, 100, v=2500)])
    assert filter_passes("volume_confirm", {"multiple": 2.0}, vol, None, None, t)
    assert not filter_passes("volume_confirm", {"multiple": 3.0}, vol, None, None, t)
