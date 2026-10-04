"""Synthetic daily frames for the scanner tests.

Each builder checks its own preconditions with the real indicators before
returning, so a fixture that drifts fails loudly instead of quietly testing
nothing.
"""

from datetime import date

import numpy as np
import pandas as pd

from backend.components.quant.indicators import Indicators

END = date(2026, 10, 2)  # a Friday


def _frame(close, high=None, low=None, volume=None, end=END) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    high = close + 1 if high is None else np.asarray(high, dtype=float)
    low = close - 1 if low is None else np.asarray(low, dtype=float)
    volume = np.full(len(close), 1000.0) if volume is None else np.asarray(volume, dtype=float)
    index = pd.bdate_range(end=end, periods=len(close))
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )


def breakout_frame(vol_mult: float = 2.0, slope: float = 0.2) -> pd.DataFrame:
    """A smooth uptrend whose last bar closes 2 above the prior 20 bars' high."""
    close = [100 + slope * i for i in range(249)]
    close.append(close[-1] + 1 + 2)
    volume = [1000.0] * 249 + [1000.0 * vol_mult]
    df = _frame(close, volume=volume)
    assert df["close"].iloc[-1] > df["high"].iloc[-21:-1].max()
    assert df["close"].iloc[-1] > Indicators.sma(df["close"], 50).iloc[-1]
    return df


def breakout_below_sma50_frame() -> pd.DataFrame:
    """Clears a 20-bar flat range after a crash, so still far under its SMA50."""
    close = [200.0] * 228 + [100.0] * 21 + [105.0]
    df = _frame(close, volume=[1000.0] * 249 + [2000.0])
    assert df["close"].iloc[-1] > df["high"].iloc[-21:-1].max()
    assert df["close"].iloc[-1] < Indicators.sma(df["close"], 50).iloc[-1]
    return df


def _uptrend_then(moves: list[float]) -> list[float]:
    close = [100 + 0.5 * i for i in range(240)]
    for move in moves:
        close.append(close[-1] + move)
    return close


def pullback_frame(variant: str | None = None) -> pd.DataFrame:
    """Uptrend, five down days of 2 into the 50-day average, then a +1 day.

    Variants each break exactly one pullback condition (RSI falling and a close
    not above the previous one cannot be separated under Wilder RSI, so those
    two variants break both).
    """
    moves = {
        None: [-2] * 5 + [1],
        "rsi_51": [-2] * 3 + [1],
        "rsi_falling": [-2] * 6,
        "close_below_prev": [-2] * 5 + [0],
        "below_sma200": [-2] * 5 + [1],
        "broke_through_sma": [-2] * 5 + [1],
    }[variant]
    close = np.asarray(_uptrend_then(moves), dtype=float)
    if variant == "below_sma200":
        close[46:121] = 400.0  # a plateau inside the 200-bar window, outside the 50-bar one
    low = close - 1
    if variant == "broke_through_sma":
        low[-3:] = close[-3:] - 8
    df = _frame(close, low=low)

    c = df["close"]
    rsi = Indicators.rsi(c)
    sma200 = Indicators.sma(c, 200).iloc[-1]
    if variant is None:
        assert 35 <= rsi.iloc[-1] <= 50 and rsi.iloc[-1] > rsi.iloc[-2]
        assert c.iloc[-1] > sma200 and Indicators.sma(c, 50).iloc[-1] > sma200
    elif variant == "rsi_51":
        assert rsi.iloc[-1] > 50
    elif variant == "below_sma200":
        assert c.iloc[-1] < sma200
    return df


def with_nan_tail(df: pd.DataFrame) -> pd.DataFrame:
    nan_row = pd.DataFrame(
        {col: [np.nan] for col in df.columns}, index=[df.index[-1] + pd.offsets.BDay(1)]
    )
    return pd.concat([df, nan_row])
