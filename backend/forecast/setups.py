"""Daily setups for Picks, as pure functions over a wide bar table.

A table is {"open"|"high"|"close"|"volume": DataFrame (rows = NIFTY's trading
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

from backend.components.quant.indicators import Indicators
from backend.datalayer.bars import NIFTY
from backend.factor.model import MONTH, YEAR, Params, scores, volatility

FIELDS = ("open", "high", "close", "volume")


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


def _top_decile(close: pd.DataFrame, rank: Callable[[object], pd.Series]) -> pd.DataFrame:
    """The top tenth of `rank(day)` (best first) on each month's first trading day."""
    out = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for day in _month_starts(close.index):
        ranked = rank(day)
        if len(ranked) >= 10:
            top = ranked.iloc[: len(ranked) // 10]
            out.loc[day, top.index] = top.values
    return out


def _ranked(t: dict, params: Params) -> pd.DataFrame:
    return _top_decile(t["close"], lambda day: scores(t["close"], day, params))


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
    return _top_decile(t["close"], lambda day: score.loc[day].dropna().sort_values(ascending=False))


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


@dataclass(frozen=True)
class Setup:
    name: str
    label: str
    horizon: int  # trading days held: entry t+1 open, exit close of t+1+horizon
    signals: Callable[[dict], pd.DataFrame]
    explain: Callable[[dict, str, object], str]


SETUPS = (
    Setup("momentum", "Momentum leader", 20, momentum,
          _explain_rank(Params(momentum_weight=1.0), "6- and 12-month momentum skipping the last month, over volatility")),
    Setup("breakout", "52-week-high breakout", 60, breakout, _explain_breakout),
    Setup("pullback", "Pullback in uptrend", 20, pullback, _explain_pullback),
    Setup("low_vol", "Low-volatility leader", 60, low_vol, _explain_low_vol),
    Setup("momentum_vol_60", "Momentum over volatility", 60, momentum_vol, _explain_momentum_vol),
)
BY_NAME = {s.name: s for s in SETUPS}
