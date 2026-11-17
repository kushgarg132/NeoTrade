"""forecast/conditions.py + variants.py: no look-ahead, the patterns, the weekly trend, timed entries."""

import numpy as np
import pandas as pd
import pytest

from backend.datalayer import bars
from backend.forecast import conditions as c
from backend.forecast import setups, variants
from backend.tests.test_forecast_picks import _frames, _table, _with_results


def _vix_frames():
    frames, stamps = _with_results(_frames())
    idx = frames[bars.NIFTY].index
    vix = 15 + 5 * np.sin(np.arange(len(idx)) / 20)
    frames[bars.INDIA_VIX] = pd.DataFrame({"open": vix, "high": vix, "low": vix, "close": vix, "volume": 0.0}, index=idx)
    return frames, stamps


@pytest.mark.parametrize("setup", variants.VARIANTS, ids=lambda s: s.name)
def test_a_variant_on_day_t_cannot_see_day_t_plus_one(setup):
    frames, stamps = _vix_frames()
    full = setup.signals(_table(frames, stamps))
    for cut in (300, 350, 419):
        day = full.index[cut]
        truncated = setup.signals(_table({s: f.loc[:day] for s, f in frames.items()}, stamps))
        pd.testing.assert_frame_equal(truncated, full.loc[:day], check_dtype=False)


def test_india_vix_is_the_vix_column_never_a_stock():
    frames, stamps = _vix_frames()
    t = _table(frames, stamps)
    assert bars.INDIA_VIX not in t["close"].columns
    assert t["vix"].iloc[-1] == pytest.approx(frames[bars.INDIA_VIX]["close"].iloc[-1])
    assert c.vix_pct(t).dropna().between(0, 1).all()


def _ohlc(rows):
    """rows of (open, high, low, close) for one stock 'A'."""
    idx = pd.bdate_range("2024-01-01", periods=len(rows))
    f = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    return {k: f[[k]].rename(columns={k: "A"}) for k in f}


def test_patterns_on_hand_built_bars():
    t = _ohlc([(10, 10.5, 9.0, 9.2), (9.0, 10.8, 8.9, 10.6), (10.5, 10.7, 9.5, 10.0)])
    assert c.bullish_engulfing(t)["A"].tolist() == [False, True, False]
    assert c.inside_bar(t)["A"].tolist() == [False, False, True]
    narrow = _ohlc([(10, 11, 9, 10)] * 6 + [(10, 10.2, 9.9, 10.1)])
    assert c.nr7(narrow)["A"].tolist() == [False] * 6 + [True]


def test_pattern_break_is_the_next_close_above_the_pattern_days_high():
    t = _ohlc([(10, 12, 8, 10), (10, 11, 9, 10), (10, 11.5, 9.5, 11.2)])  # day 1 inside, day 2 closes above 11
    assert c.pattern_break(t, c.inside_bar)["A"].tolist() == [False, False, True]


def test_the_weekly_trend_uses_completed_weeks_only_and_survives_a_friday_holiday():
    days = pd.bdate_range("2024-01-01", periods=200)
    days = days[~((days.dayofweek == 4) & (days.day < 8))]  # first Friday of each month is a holiday
    close = pd.DataFrame({"A": np.linspace(100, 300, len(days))}, index=days)
    w = c.weekly_trend({"close": close})["A"]
    week = days.to_period("W-FRI")
    assert (w.groupby(week).nunique(dropna=False) == 1).all()  # constant inside a week: the current week never counts
    assert w.dropna().gt(0).all() and w.notna().sum() > 0


def test_a_timed_entry_fires_on_the_first_break_within_the_wait_and_not_after_it():
    t = _ohlc([(10, 12, 8, 10), (10, 11, 9, 10), (10, 11.5, 9.5, 11.2), (11, 12, 10.9, 11.5)])
    base = setups.Setup("x", "X", 5, lambda t: pd.DataFrame({"A": [2.0, np.nan, np.nan, np.nan]}, index=t["close"].index),
                        lambda *a: "")
    fired = c.timed(base, "x@ib", "X", c.inside_bar, "inside bar").signals(t)["A"]
    assert fired.tolist()[2] == 2.0 and fired.isna().sum() == 3
    late = c.timed(base, "x@ib", "X", c.inside_bar, "inside bar", wait=1).signals(t)["A"]
    assert late.isna().all()


def test_breadth_counts_only_the_days_members():
    days = pd.bdate_range("2023-01-02", periods=210)
    up, down = np.linspace(100, 200, 210), np.linspace(200, 100, 210)
    close = pd.DataFrame({f"U{i}": up for i in range(10)} | {f"D{i}": down for i in range(10)}, index=days)
    member = pd.DataFrame(True, index=days, columns=close.columns)
    assert c.breadth({"close": close}).iloc[-1] == pytest.approx(0.5)
    member[[f"D{i}" for i in range(10)]] = False
    assert c.breadth({"close": close, "member": member}).iloc[-1] == pytest.approx(1.0)
    member[["U0"]] = False
    assert np.isnan(c.breadth({"close": close, "member": member}).iloc[-1])  # 9 members: too few to count


def test_every_variant_is_experimental_and_named_once():
    names = [v.name for v in variants.VARIANTS]
    assert len(names) == len(set(names)) and all(v.experimental for v in variants.VARIANTS)
    assert not set(names) & set(setups.BY_NAME)


def test_hammer_needs_a_fall_and_a_long_lower_shadow():
    fall = [(15 - i, 15.2 - i, 14.8 - i, 14.9 - i) for i in range(6)]
    t = _ohlc(fall + [(9.6, 9.72, 8.5, 9.7)])  # body 0.1, lower shadow 1.1, upper 0.02
    assert c.hammer(t)["A"].tolist() == [False] * 6 + [True]


def test_morning_star_is_long_red_small_body_then_green_past_the_midpoint():
    t = _ohlc([(12, 12.1, 9.9, 10), (9.8, 10, 9.5, 9.85), (9.9, 11.5, 9.8, 11.3)])
    assert c.morning_star(t)["A"].tolist() == [False, False, True]
