"""find_setups: the two named setups, on completed bars only, with ATR stops."""

from datetime import date, datetime

import pytest

from backend.components.quant.indicators import Indicators
from backend.engine.session import IST
from backend.research.scanner import find_setups
from backend.tests.scanner_frames import (
    _frame,
    breakout_below_sma50_frame,
    breakout_frame,
    pullback_frame,
    with_nan_tail,
)

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=IST)  # Monday; the frames end Friday


def _atr(df):
    return Indicators.atr(df["high"], df["low"], df["close"]).iloc[-1]


def test_breakout_fires():
    df = breakout_frame()
    close, atr = df["close"].iloc[-1], _atr(df)
    found = find_setups({"AAA": df}, ["AAA"], NOW).findings
    assert [x.setup for x in found] == ["breakout"]
    stop = round(close - 2 * atr, 2)
    assert found[0].stop == stop
    assert found[0].target == round(close + 2 * (close - stop), 2)
    assert found[0].risk_pct == round((close - stop) / close * 100, 2)
    assert any("20-day high" in r for r in found[0].reasons)
    assert any("20-day average" in r for r in found[0].reasons)


def test_breakout_needs_1_5x_volume():
    assert find_setups({"AAA": breakout_frame(vol_mult=1.49)}, ["AAA"], NOW).findings == []


def test_breakout_needs_close_above_sma50():
    assert find_setups({"AAA": breakout_below_sma50_frame()}, ["AAA"], NOW).findings == []


def test_pullback_fires():
    df = pullback_frame()
    found = find_setups({"BBB": df}, ["BBB"], NOW).findings
    assert [x.setup for x in found] == ["pullback"]
    assert found[0].stop == round(df["low"].iloc[-3:].min() - 0.5 * _atr(df), 2)
    assert any("RSI" in r for r in found[0].reasons)


@pytest.mark.parametrize(
    "variant", ["rsi_51", "rsi_falling", "below_sma200", "broke_through_sma", "close_below_prev"]
)
def test_pullback_rejects(variant):
    assert find_setups({"BBB": pullback_frame(variant)}, ["BBB"], NOW).findings == []


@pytest.mark.parametrize("hhmm,as_of", [((15, 29), date(2026, 10, 2)), ((15, 31), date(2026, 10, 5))])
def test_partial_bar_dropped_before_close(hhmm, as_of):
    now = datetime(2026, 10, 5, *hhmm, tzinfo=IST)
    frame = _frame([100.0] * 250, end=date(2026, 10, 5))
    assert find_setups({"AAA": frame}, ["AAA"], now).as_of == as_of


def test_skipped_reasons():
    result = find_setups({"SHORT": _frame([100.0] * 150)}, ["SHORT", "GONE"], NOW)
    assert {(s.symbol, s.reason) for s in result.skipped} == {
        ("SHORT", "under 200 bars"),
        ("GONE", "no data"),
    }
    assert result.scanned == 2 and result.findings == []


def test_nan_last_row_is_dropped():
    result = find_setups({"AAA": with_nan_tail(breakout_frame())}, ["AAA"], NOW)
    assert len(result.findings) == 1
    assert "NaN" not in result.model_dump_json()


def test_sorted_by_return_3m():
    frames = {"LOW": breakout_frame(slope=0.1), "HIGH": breakout_frame(slope=0.4)}
    assert [x.symbol for x in find_setups(frames, ["LOW", "HIGH"], NOW).findings] == ["HIGH", "LOW"]
