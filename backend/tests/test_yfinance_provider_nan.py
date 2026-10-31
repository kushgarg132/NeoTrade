"""yfinance leaves NaN on half-filled rows. The stock chart's intraday feed must drop a NaN close
(NaN is not JSON: Starlette refuses it with a 500) and survive a NaN volume (int(nan) raised)."""

import asyncio
import math

import pandas as pd

from backend.data.providers import yfinance_provider as yp


class _T:
    def __init__(self, df):
        self.df = df

    def history(self, period, interval):
        return self.df


def _run(monkeypatch, df):
    monkeypatch.setattr(yp.yf, "Ticker", lambda s: _T(df))
    p = yp.YFinanceProvider()
    monkeypatch.setattr(p, "_ticker_symbol", lambda inst: "INFY.NS")
    return asyncio.run(p.history(None, interval="5m", period="1d"))


def test_nan_close_rows_are_dropped_and_nan_volume_is_zero(monkeypatch):
    idx = pd.date_range("2026-10-30 09:15", periods=3, freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame({"Open": [1.0, 2.0, 3.0], "High": [1.0, 2.0, 3.0], "Low": [1.0, 2.0, 3.0],
                       "Close": [1.0, float("nan"), 3.0], "Volume": [10.0, 20.0, float("nan")]}, index=idx)
    candles = _run(monkeypatch, df)
    assert [c.close for c in candles] == [1.0, 3.0]
    assert candles[-1].volume == 0


def test_nan_open_high_low_fall_back_to_the_close(monkeypatch):
    idx = pd.date_range("2026-10-30 09:15", periods=1, freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame({"Open": [float("nan")], "High": [float("nan")], "Low": [float("nan")],
                       "Close": [5.0], "Volume": [1.0]}, index=idx)
    (c,) = _run(monkeypatch, df)
    assert (c.open, c.high, c.low) == (5.0, 5.0, 5.0)
    assert not any(math.isnan(v) for v in (c.open, c.high, c.low, c.close))
