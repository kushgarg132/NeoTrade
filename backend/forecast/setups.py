"""Daily setups for Picks, as pure functions over a wide bar table.

A table is {"open"|"high"|"low"|"close"|"volume": DataFrame (rows = NIFTY's trading
days, columns = symbols), "nifty_open"|"nifty_close": Series}. NIFTY's days
are the calendar, so a Yahoo bar on an exchange holiday drops out.

A setup's `signals(table)` is a frame of strengths (higher = stronger, NaN =
did not fire). NO LOOK-AHEAD: the value on day t uses rows up to and
including t only (backward rolling windows, `factor.model.scores` sliced to
t), so truncating the table after t never changes it -- tested.
"""

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from backend.strategies.indicators import Indicators
from backend.datalayer.bars import NIFTY
from backend.factor.model import MONTH, YEAR, Params, scores, volatility

FIELDS = ("open", "high", "low", "close", "volume")


def table(frames: dict[str, pd.DataFrame]) -> dict:
    """frames from `datalayer.bars.read` -> the wide table (NIFTY must be in it)."""
    nifty = frames[NIFTY]
    days = nifty.index
    stocks = {s: f for s, f in frames.items() if s != NIFTY}
    out = {f: pd.DataFrame({s: df[f] for s, df in stocks.items()}).reindex(days) for f in FIELDS}
    out["nifty_open"], out["nifty_close"] = nifty["open"], nifty["close"]
    return out


def _month_starts(days: pd.DatetimeIndex) -> list:
    """First trading day of each month: known on the day itself (the previous
    session was in another month), unlike month-end."""
    return [d for prev, d in zip(days[:-1], days[1:]) if d.month != prev.month]


def _in_index(t: dict, day, s: pd.Series) -> pd.Series:
    """`s` cut to the stocks in the index on `day` (`t["member"]`), so ranks are taken among them."""
    m = t.get("member")
    return s if m is None else s[m.loc[day].reindex(s.index, fill_value=False).to_numpy()]


def _top_decile(t: dict, rank: Callable[[object], pd.Series]) -> pd.DataFrame:
    """The top tenth of `rank(day)` (best first), among index members, on each month's first trading day."""
    close = t["close"]
    out = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for day in _month_starts(close.index):
        ranked = _in_index(t, day, rank(day))
        if len(ranked) >= 10:
            top = ranked.iloc[: len(ranked) // 10]
            out.loc[day, top.index] = top.values
    return out


def _ranked(t: dict, params: Params) -> pd.DataFrame:
    return _top_decile(t, lambda day: scores(t["close"], day, params))


def momentum(t: dict) -> pd.DataFrame:
    return _ranked(t, Params(momentum_weight=1.0))


def low_vol(t: dict) -> pd.DataFrame:
    return _ranked(t, Params(momentum_weight=0.0))


VOL_DAYS = 60


def _mom_vol_parts(close: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """12-1 month return (the last month skipped) and 60-day daily volatility."""
    r12_1 = close.shift(MONTH) / close.shift(YEAR) - 1
    return r12_1, close.pct_change(fill_method=None).rolling(VOL_DAYS).std()


def momentum_vol(t: dict) -> pd.DataFrame:
    r12_1, vol = _mom_vol_parts(t["close"])
    score = r12_1 / vol.replace(0, np.nan)
    return _top_decile(t, lambda day: score.loc[day].dropna().sort_values(ascending=False))


def breakout(t: dict) -> pd.DataFrame:
    close, volume = t["close"], t["volume"]
    high_52w = close.rolling(YEAR, min_periods=YEAR).max()
    avg_vol = volume.shift(1).rolling(20, min_periods=20).mean()
    ratio = volume / avg_vol
    return ratio.where((close >= high_52w) & (ratio >= 1.5))


def pullback(t: dict) -> pd.DataFrame:
    close = t["close"]
    sma200 = close.rolling(200, min_periods=200).mean()
    rsi = Indicators.rsi(close, 14)
    return (35 - rsi).where((close > sma200) & (rsi < 35))


def _explain_rank(params: Params, what: str):
    def explain(t: dict, symbol: str, day) -> str:
        ranked = scores(t["close"], day, params)
        rank = list(ranked.index).index(symbol) + 1 if symbol in ranked.index else None
        return f"ranked #{rank} of {len(ranked)} on {what} (top decile, re-ranked each month)"
    return explain


def _explain_breakout(t: dict, symbol: str, day) -> str:
    close, volume = t["close"][symbol].loc[:day], t["volume"][symbol].loc[:day]
    ratio = volume.iloc[-1] / volume.iloc[-21:-1].mean()
    return f"closed at a 52-week high (₹{close.iloc[-1]:,.2f}) on {ratio:.1f}x its 20-day average volume"


def _explain_pullback(t: dict, symbol: str, day) -> str:
    close = t["close"][symbol].loc[:day]
    rsi = Indicators.rsi(close, 14).iloc[-1]
    above = close.iloc[-1] / close.iloc[-200:].mean() - 1
    return f"RSI(14) fell to {rsi:.1f} while the close stays {above:.1%} above its 200-day average"


def _explain_low_vol(t: dict, symbol: str, day) -> str:
    vol = volatility(t["close"], day).dropna().sort_values()
    rank = list(vol.index).index(symbol) + 1 if symbol in vol.index else None
    return f"1-year volatility {vol.get(symbol, np.nan):.0%}, #{rank} lowest of {len(vol)} (re-ranked each month)"


def _explain_momentum_vol(t: dict, symbol: str, day) -> str:
    close = t["close"].loc[:day]
    r12_1, vol = (part.iloc[-1] for part in _mom_vol_parts(close))
    ranked = (r12_1 / vol.replace(0, np.nan)).dropna().sort_values(ascending=False)
    rank = list(ranked.index).index(symbol) + 1 if symbol in ranked.index else None
    return (f"12-month return skipping the last month {r12_1[symbol]:+.0%} over 60-day volatility "
            f"{vol[symbol] * np.sqrt(YEAR):.0%} (annualised): #{rank} of {len(ranked)} "
            f"(top decile, re-ranked each month)")


RS_DAYS = 126


def _rs(t: dict) -> pd.DataFrame:
    """126-day return minus NIFTY's."""
    return t["close"].pct_change(RS_DAYS, fill_method=None).sub(t["nifty_close"].pct_change(RS_DAYS), axis=0)


def rs_leaders_regime(t: dict) -> pd.DataFrame:
    """Month's first trading day: top decile of 126-day relative strength vs NIFTY, close above a rising 50- and
    200-day average (rising = higher than 20 days ago), and NIFTY above its own 200-day average that day."""
    close = t["close"]
    rs = _rs(t)
    s50, s200 = close.rolling(50, min_periods=50).mean(), close.rolling(200, min_periods=200).mean()
    trend = (close > s50) & (close > s200) & (s50 > s50.shift(20)) & (s200 > s200.shift(20))
    nc = t["nifty_close"]
    bull = nc > nc.rolling(200, min_periods=200).mean()
    out = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for day in _month_starts(close.index):
        r = _in_index(t, day, rs.loc[day].dropna())
        if len(r) < 10 or not bull.loc[day]:
            continue
        top = r[r >= r.quantile(0.9)]
        top = top[trend.loc[day, top.index]]
        out.loc[day, top.index] = top.values
    return out


def _explain_rs_leaders(t: dict, symbol: str, day) -> str:
    rs = _rs(t).loc[day, symbol]
    stock = t["close"][symbol].pct_change(RS_DAYS, fill_method=None).loc[day]
    return (f"126-day return {stock:+.0%} vs NIFTY {stock - rs:+.0%}: top decile of relative strength on the month's first day, "
            f"above a rising 50- and 200-day average, with NIFTY above its 200-day average")


def _vol_ratio(t: dict) -> pd.DataFrame:
    """Each day's volume over the previous 20 days' average."""
    v = t["volume"]
    return v / v.shift(1).rolling(20, min_periods=20).mean()


def results_drift(t: dict, move_min=0.04, vol_min=2.0, gap=False, days=0) -> pd.DataFrame:
    """Post-results drift. The reaction day is the first session on or after the announcement (IST), or the next one
    when it came after 15:00. It qualifies when the close (or, with `gap`, the open) is >= move_min above the prior
    close on >= vol_min x its 20-day volume. Fires on that close, or `days` later if every close since held the prior
    close. `t["results"]` = {symbol: [announcement datetimes, IST]} (`datalayer/results.py`; patchy for small caps)."""
    close, idx = t["close"], t["close"].index
    px = t["open"] if gap else close
    cond = ((px / close.shift(1) - 1) >= move_min) & (_vol_ratio(t) >= vol_min)
    out = pd.DataFrame(np.nan, index=idx, columns=close.columns)
    for sym, stamps in t.get("results", {}).items():
        if sym not in close.columns:
            continue
        col = close.columns.get_loc(sym)
        for ts in stamps:
            i = idx.searchsorted(pd.Timestamp(ts.date()) + pd.Timedelta(days=int(ts.hour >= 15)))
            j = i + days
            if i < 1 or j >= len(idx) or not cond.iat[i, col]:
                continue
            c = close[sym]
            if days and (c.iloc[i + 1:j + 1] < c.iat[i - 1]).any():
                continue
            out.iat[j, col] = px[sym].iat[i] / c.iat[i - 1] - 1
    return out


def _explain_results(t: dict, symbol: str, day) -> str:
    c = t["close"][symbol]
    i = c.index.get_loc(day)
    return (f"Results day: closed {c.iat[i] / c.iat[i - 1] - 1:+.1%} on {_vol_ratio(t)[symbol].iat[i]:.1f}x its 20-day "
            f"volume (a move of 4%+ on 2x volume after results)")


@dataclass(frozen=True)
class Setup:
    name: str
    label: str
    horizon: int  # trading days held: entry t+1 open, exit close of t+1+horizon
    signals: Callable[[dict], pd.DataFrame]
    explain: Callable[[dict, str, object], str]
    experimental: bool = False  # shown with an "Experimental" badge; still subject to the edge rule


SETUPS = (
    Setup("momentum", "Momentum leader", 20, momentum,
          _explain_rank(Params(momentum_weight=1.0), "6- and 12-month momentum skipping the last month, over volatility")),
    Setup("breakout", "52-week-high breakout", 60, breakout, _explain_breakout),
    Setup("pullback", "Pullback in uptrend", 20, pullback, _explain_pullback),
    Setup("low_vol", "Low-volatility leader", 60, low_vol, _explain_low_vol),
    Setup("momentum_vol_60", "Momentum over volatility", 60, momentum_vol, _explain_momentum_vol),
    Setup("rs_leaders_regime", "Relative-strength leader", 60, rs_leaders_regime, _explain_rs_leaders, experimental=True),
    # Same monthly ranking held ~one month (re-ranked at the next month start). 2026-10-26 check on prod bars:
    # adjusted OOS excess +1.42%, t 3.21 over 6 variants tried that day (new_setups_tool had flagged it 2026-10-22).
    Setup("rs_leaders_20", "Relative-strength leader (1 month)", 20, rs_leaders_regime, _explain_rs_leaders, experimental=True),
    # new_setups_tool 2026-10-27 (results_up4_vol2, prod bars + yfinance dates, members only): h=40 OOS excess +2.3%,
    # 16/17 years, Bonferroni over 69 trials; over the same-month baseline +1.5% t 2.0 (below the strict bar).
    Setup("results_drift", "Post-results drift", 40, results_drift, _explain_results, experimental=True),
)
BY_NAME = {s.name: s for s in SETUPS}
