"""Standard return metrics (empyrical-reloaded) and the trade-to-daily-return series."""
import math
from datetime import datetime, timedelta

import empyrical
import pandas as pd

KEYS = ("cagr", "sharpe", "sortino", "max_drawdown", "volatility", "alpha", "beta")


def _f(x) -> float | None:
    x = float(x)
    return x if math.isfinite(x) else None


def summary(daily_returns: pd.Series, benchmark: pd.Series | None = None) -> dict:
    r = daily_returns.dropna()
    if len(r) < 2:
        return dict.fromkeys(KEYS)
    out = {"cagr": empyrical.annual_return(r), "sharpe": empyrical.sharpe_ratio(r),
           "sortino": empyrical.sortino_ratio(r), "max_drawdown": empyrical.max_drawdown(r),
           "volatility": empyrical.annual_volatility(r), "alpha": None, "beta": None}
    if benchmark is not None and len(benchmark.dropna()) > 1:
        out["alpha"], out["beta"] = empyrical.alpha_beta(r, benchmark)
    return {k: None if v is None else _f(v) for k, v in out.items()}


def daily_returns(trades: list[dict], start: datetime, end: datetime, account: float) -> pd.Series:
    """Net P&L per weekday as a fraction of the account, zero on days
    without a trade, over [start, end)."""
    days = pd.bdate_range(start.date(), end.date() - timedelta(days=1))
    pnl = pd.Series(0.0, index=days)
    for t in trades:
        day = pd.Timestamp(datetime.fromisoformat(t["timestamp"]).date())
        if day in pnl.index:
            pnl[day] += t["net_pnl"]
    return pnl / account
