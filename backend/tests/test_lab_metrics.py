from datetime import datetime

import empyrical
import numpy as np
import pandas as pd
import pytest

from backend.lab.metrics import daily_returns, summary


def test_summary_matches_empyrical():
    r = pd.Series(np.random.default_rng(0).normal(0.0005, 0.01, 500), index=pd.bdate_range("2024-01-01", periods=500))
    s = summary(r)
    assert s["sharpe"] == pytest.approx(empyrical.sharpe_ratio(r))
    assert s["max_drawdown"] == pytest.approx(empyrical.max_drawdown(r))
    assert s["alpha"] is None and s["beta"] is None
    assert summary(r, r)["beta"] == pytest.approx(1.0)


def test_summary_short_series_is_all_none():
    assert set(summary(pd.Series([0.01])).values()) == {None}


def test_daily_returns_puts_pnl_on_the_trade_day():
    trades = [{"timestamp": "2024-01-03T10:00:00", "net_pnl": 5000.0}]  # a Wednesday
    r = daily_returns(trades, datetime(2024, 1, 1), datetime(2024, 1, 6), 1_000_000.0)
    assert len(r) == 5 and r[pd.Timestamp("2024-01-03")] == pytest.approx(0.005) and r.sum() == pytest.approx(0.005)


def test_daily_returns_skips_nse_holidays():
    r = daily_returns([], datetime(2026, 10, 19), datetime(2026, 10, 24), 1_000_000.0)  # Tue 10-20 closed
    assert pd.Timestamp("2026-10-20") not in r.index and len(r) == 4
