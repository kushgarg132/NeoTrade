"""Market and chart conditions for the Picks study: breadth, India VIX, the weekly trend and
candlestick patterns, plus the two ways a setup uses them (`gated`, `timed`).

Same contract as `setups.py`: pure functions over the wide table, and NO LOOK-AHEAD -- the
value on day t uses rows up to and including t only (the weekly trend uses completed weeks
only), so truncating the table after t never changes it (tests/test_forecast_conditions.py).

Each condition is tested as a variant of an existing setup by `forecast/variants.py`; a
variant joins `setups.SETUPS` only when it passes the study's corrected bar there.
"""

from dataclasses import replace

import numpy as np
import pandas as pd

YEAR = 252

# --- market: breadth and India VIX (one value per day) ----------------------------------

BREADTH_DAYS = 200
BREADTH_MIN = 0.5      # gate: at least half the index members above their 200-day average
VIX_Q = 0.8            # gate: India VIX at or below its own trailing-year 80th percentile


def breadth(t: dict) -> pd.Series:
    """Share of the day's index members (`t["member"]`, else every stock) closing above their own
    200-day average, among those with 200 closes. NaN with fewer than 10 such stocks."""
    close = t["close"]
    sma = close.rolling(BREADTH_DAYS, min_periods=BREADTH_DAYS).mean()
    known = sma.notna()
    m = t.get("member")
    if m is not None:
        known &= m.reindex(index=close.index, columns=close.columns, fill_value=False)
    above = (close > sma) & known
    n = known.sum(axis=1)
    return (above.sum(axis=1) / n).where(n >= 10)


def vix_pct(t: dict) -> pd.Series:
    """India VIX's close as a percentile of its trailing year (0..1), NaN without VIX bars."""
    vix = t.get("vix")
    if vix is None:
        return pd.Series(np.nan, index=t["close"].index)
    vix = vix.reindex(t["close"].index)
    return vix.rolling(YEAR, min_periods=YEAR // 2).rank(pct=True)


def breadth_ok(t: dict) -> pd.Series:
    return breadth(t) >= BREADTH_MIN


def vix_ok(t: dict) -> pd.Series:
    return vix_pct(t) <= VIX_Q


# --- stock: the weekly trend -------------------------------------------------------------

WEEKS = 30


def weekly_trend(t: dict) -> pd.DataFrame:
    """Last completed week's close over its 30-week average, minus 1, per stock and day. A week
    is complete once a later week has started, so the current week never counts (no look-ahead,
    and a Friday holiday cannot hide a week)."""
    close = t["close"]
    week = close.index.to_period("W-FRI")
    weekly = close.groupby(week).last()
    trend = weekly / weekly.rolling(WEEKS, min_periods=WEEKS).mean() - 1
    return pd.DataFrame(trend.shift(1).reindex(week).to_numpy(), index=close.index, columns=close.columns)


def weekly_up(t: dict) -> pd.DataFrame:
    return weekly_trend(t) > 0


# --- candlestick patterns (daily OHLC, per stock) ----------------------------------------


def _parts(t: dict):
    o, h, l, c = (t[k] for k in ("open", "high", "low", "close"))
    body = (c - o).abs()
    rng = h - l
    return o, h, l, c, body, rng


def doji(t: dict) -> pd.DataFrame:
    _, _, _, _, body, rng = _parts(t)
    return (rng > 0) & (body <= 0.1 * rng)


def hammer(t: dict) -> pd.DataFrame:
    """Long lower shadow (2x the body), small upper one, after a 5-day fall."""
    o, h, l, c, body, rng = _parts(t)
    lower, upper = np.minimum(o, c) - l, h - np.maximum(o, c)
    return (rng > 0) & (body > 0) & (lower >= 2 * body) & (upper <= 0.5 * body) & (c < c.shift(5))


def bullish_engulfing(t: dict) -> pd.DataFrame:
    o, _, _, c, _, _ = _parts(t)
    o1, c1 = o.shift(1), c.shift(1)
    return (c1 < o1) & (c > o) & (o <= c1) & (c >= o1)


def morning_star(t: dict) -> pd.DataFrame:
    """A long red day, a small-bodied day, then a green close above the red body's midpoint."""
    o, _, _, c, body, rng = _parts(t)
    o2, c2, b2, r2 = o.shift(2), c.shift(2), body.shift(2), rng.shift(2)
    return (c2 < o2) & (b2 >= 0.6 * r2) & (body.shift(1) <= 0.3 * b2) & (c > o) & (c > (o2 + c2) / 2)


def three_white_soldiers(t: dict) -> pd.DataFrame:
    o, _, _, c, _, _ = _parts(t)
    out = None
    for k in range(3):
        green = c.shift(k) > o.shift(k)
        out = green if out is None else out & green
    for k in range(2):  # each close higher, each open inside the previous body
        out &= (c.shift(k) > c.shift(k + 1)) & (o.shift(k) > o.shift(k + 1)) & (o.shift(k) < c.shift(k + 1))
    return out


def inside_bar(t: dict) -> pd.DataFrame:
    _, h, l, _, _, _ = _parts(t)
    return (h < h.shift(1)) & (l > l.shift(1))


def nr7(t: dict) -> pd.DataFrame:
    """Narrowest high-low range of the last 7 days."""
    _, _, _, _, _, rng = _parts(t)
    return (rng > 0) & (rng <= rng.rolling(7, min_periods=7).min())


PATTERNS = {
    "doji": doji, "hammer": hammer, "bullish_engulfing": bullish_engulfing, "morning_star": morning_star,
    "three_white_soldiers": three_white_soldiers, "inside_bar": inside_bar, "nr7": nr7,
}


def pattern_break(t: dict, pattern) -> pd.DataFrame:
    """The day after a pattern day, closing above the pattern day's high."""
    return pattern(t).shift(1, fill_value=False) & (t["close"] > t["high"].shift(1))


# --- using them: a setup gated by a condition, or entered on a pattern break -------------

TIMING_DAYS = 10  # a timed entry waits at most this many sessions after the setup fired


def _frame(cond, like: pd.DataFrame) -> pd.DataFrame:
    """A per-day Series or a per-stock frame -> a boolean frame shaped like `like` (NaN = False)."""
    if isinstance(cond, pd.Series):
        return pd.DataFrame(np.repeat(cond.fillna(False).astype(bool).to_numpy()[:, None], like.shape[1], axis=1),
                            index=like.index, columns=like.columns)
    return cond.reindex(index=like.index, columns=like.columns).fillna(False).astype(bool)


def gated(setup, name: str, label: str, cond, explain_extra: str):
    """`setup` firing only where `cond(t)` holds on the signal day."""
    def signals(t):
        fires = setup.signals(t)
        return fires.where(_frame(cond(t), fires))

    def explain(t, symbol, day):
        return f"{setup.explain(t, symbol, day)}; {explain_extra}"

    return replace(setup, name=name, label=label, signals=signals, explain=explain, experimental=True)


def timed(setup, name: str, label: str, pattern, pattern_label: str, wait: int = TIMING_DAYS):
    """`setup` entered on the first pattern break within `wait` sessions after it fired (the setup's
    strength carried over), instead of the day it fired. No break in time: no entry."""
    def signals(t):
        fires = setup.signals(t)
        trigger = _frame(pattern_break(t, pattern), fires).to_numpy()
        f = fires.to_numpy()
        out = np.full(f.shape, np.nan)
        for p, j in zip(*np.nonzero(~np.isnan(f))):
            hits = np.flatnonzero(trigger[p + 1:p + 1 + wait, j])
            if hits.size:
                k = p + 1 + hits[0]
                out[k, j] = f[p, j] if np.isnan(out[k, j]) else max(out[k, j], f[p, j])
        return pd.DataFrame(out, index=fires.index, columns=fires.columns)

    def explain(t, symbol, day):
        return f"{setup.label} fired within the last {wait} sessions; entered on a close above the prior {pattern_label}'s high"

    return replace(setup, name=name, label=label, signals=signals, explain=explain, experimental=True)


def standalone(name: str, pattern, horizon: int = 20):
    """A pattern as its own setup (strength 1): the control, expected to fail after costs."""
    from backend.forecast.setups import Setup

    label = name.replace("_", " ").capitalize()

    def signals(t):
        return pattern(t).astype(float).where(pattern(t))

    return Setup(f"candle_{name}", f"Candle: {label}", horizon, signals,
                 lambda t, s, d: f"{label} candle", experimental=True)
