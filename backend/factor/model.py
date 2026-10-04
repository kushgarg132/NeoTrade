"""The core long-term strategy, as pure functions over a daily close table
(rows = trading days, columns = symbols, adjusted closes).

Momentum + low volatility, held as a portfolio and rebalanced on a
calendar -- the evidence-based alternative to per-symbol entry signals
(docs/ROADMAP.md, "evidence-based core strategy"):

- momentum: 6- and 12-month return skipping the latest month, each divided
  by 1-year volatility (the NIFTY200 Momentum 30 recipe);
- low volatility: lower 1-year volatility ranks higher;
- hold the top N by the blended score, with a buffer so a holding is only
  sold once it falls well out of favour (turnover and STT are the enemy);
- weight by inverse volatility, capped per name;
- scale total exposure to a target volatility, and go to the risk-off
  sleeve (a liquid ETF) whenever the market trades below its 200-day SMA.

Every function looks only at data up to and including `t`.
"""

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

YEAR, HALF, MONTH = 252, 126, 21


@dataclass(frozen=True)
class Params:
    momentum_weight: float = 0.5   # 1.0 = pure momentum, 0.0 = pure low-vol
    top_n: int = 20
    buffer: int = 30               # a holding is kept while it ranks within this
    weight_cap: float = 0.10
    target_vol: Optional[float] = 0.15  # annualised; None = always fully invested when risk-on
    trend_days: int = 200
    rebalance: str = "monthly"     # or "quarterly"
    avoid: frozenset = field(default_factory=frozenset)


def _zscore(values: pd.Series) -> pd.Series:
    std = values.std()
    return (values - values.mean()) / std if std and np.isfinite(std) else values * 0.0


def volatility(closes: pd.DataFrame, t) -> pd.Series:
    """Annualised volatility of daily returns over the year ending at t."""
    window = closes.loc[:t].iloc[-(YEAR + 1):]
    return window.pct_change(fill_method=None).std() * np.sqrt(YEAR)


def scores(closes: pd.DataFrame, t, params: Params, avoid: Optional[set] = None) -> pd.Series:
    """Blended score per symbol with a full year of history at t, best first."""
    past = closes.loc[:t]
    if len(past) <= YEAR:
        return pd.Series(dtype=float)
    complete = past.iloc[-(YEAR + 1):].notna().all()
    blocked = {s.upper() for s in (avoid or set()) | set(params.avoid)}
    symbols = [s for s in past.columns if complete[s] and s.upper() not in blocked]
    if not symbols:
        return pd.Series(dtype=float)
    p = past[symbols]
    vol = volatility(p, t).replace(0, np.nan)
    skip = p.iloc[-1 - MONTH]
    r6 = skip / p.iloc[-1 - HALF] - 1
    r12 = skip / p.iloc[-1 - YEAR] - 1
    momentum = (_zscore(r6 / vol) + _zscore(r12 / vol)) / 2
    low_vol = _zscore(-vol)
    blended = params.momentum_weight * momentum + (1 - params.momentum_weight) * low_vol
    return blended.dropna().sort_values(ascending=False)


def select(ranked: pd.Series, held: set, top_n: int, buffer: int) -> list[str]:
    """Top `top_n`, but a current holding is kept while it ranks within
    `buffer` -- fewer trades for the same exposure to the factor."""
    order = list(ranked.index)
    rank = {s: i for i, s in enumerate(order)}
    kept = [s for s in order if s in held and rank[s] < buffer][:top_n]
    for s in order:
        if len(kept) >= top_n:
            break
        if s not in kept:
            kept.append(s)
    return kept


def weights(vols: pd.Series, cap: float) -> pd.Series:
    """Inverse-volatility weights summing to 1, no name above `cap`
    (excess redistributed pro rata; if the cap cannot bind, equal weights)."""
    if vols.empty:
        return vols
    if cap * len(vols) <= 1:
        return pd.Series(1 / len(vols), index=vols.index)
    raw = 1 / vols.clip(lower=1e-6)
    w = raw / raw.sum()
    for _ in range(len(w)):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        free = ~over & (w < cap)
        w[free] += excess * w[free] / w[free].sum()
    return w


def exposure(market: pd.Series, book_returns: pd.Series, t, params: Params) -> float:
    """Fraction of capital in stocks: 0 when the market is below its trend
    SMA, else min(1, target_vol / the book's recent volatility)."""
    past = market.loc[:t].dropna()
    if len(past) >= params.trend_days and past.iloc[-1] < past.iloc[-params.trend_days:].mean():
        return 0.0
    if params.target_vol is None:
        return 1.0
    recent = book_returns.loc[:t].dropna().iloc[-63:]
    realised = recent.std() * np.sqrt(YEAR) if len(recent) > 20 else 0.0
    if not realised or not np.isfinite(realised):
        return 1.0
    return float(min(1.0, params.target_vol / realised))


def target_book(closes: pd.DataFrame, market: pd.Series, t, held: set, params: Params,
                avoid: Optional[set] = None) -> tuple[pd.Series, float]:
    """Target weights (summing to the stock exposure) at t, and that exposure.
    The rest of the capital belongs to the risk-off sleeve."""
    ranked = scores(closes, t, params, avoid)
    chosen = select(ranked, held, params.top_n, params.buffer)
    if not chosen:
        return pd.Series(dtype=float), 0.0
    vols = volatility(closes[chosen], t)
    w = weights(vols, params.weight_cap)
    book = closes[chosen].loc[:t].pct_change(fill_method=None).iloc[-64:].fillna(0) @ w
    level = exposure(market, book, t, params)
    return w * level, level
