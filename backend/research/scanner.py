"""The scanner: two named setups over the user's universe, on completed daily
bars, with volatility-based stops.

- **Breakout:** close above the prior 20 bars' high, on at least 1.5x their
  average volume, above the 50-day average. Stop = close - 2 ATR.
- **Pullback in uptrend:** above the 200-day average with the 50 over the 200,
  a low in the last 3 bars that touched (not broke through) the 20- or 50-day
  average, RSI 35-50 and rising, and a close above the previous one.
  Stop = lowest low of the last 3 bars - 0.5 ATR.

Target is 2R for both. A stock matching both is reported once, as a breakout.
`find_setups` is pure (no I/O); findings are leads, not advice.
"""

from datetime import date, datetime, time
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel

from backend.components.quant.indicators import Indicators
from backend.engine.session import IST

_MIN_BARS = 200
_MARKET_CLOSE = time(15, 30)
_BARS_3M = 63


class Finding(BaseModel):
    symbol: str
    setup: Literal["breakout", "pullback"]
    close: float
    change_pct: float
    stop: float
    target: float
    risk_pct: float
    return_3m: float
    reasons: list[str]


class Skipped(BaseModel):
    symbol: str
    reason: Literal["no data", "under 200 bars"]


class ScanResult(BaseModel):
    as_of: Optional[date]
    scanned: int
    skipped: list[Skipped]
    findings: list[Finding]


def _rupees(x: float) -> str:
    return f"₹{x:,.2f}"


def _completed(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    df = df.dropna(subset=["close", "high", "low"])
    local = now.astimezone(IST)
    if len(df) and df.index[-1].date() == local.date() and local.time() < _MARKET_CLOSE:
        df = df.iloc[:-1]
    return df


def _breakout(df: pd.DataFrame, sma50: pd.Series, atr: float):
    close = df["close"].iloc[-1]
    prior_high = df["high"].iloc[-21:-1].max()
    avg_volume = df["volume"].iloc[-21:-1].mean()
    ratio = df["volume"].iloc[-1] / avg_volume if avg_volume > 0 else 0.0
    if close > prior_high and ratio >= 1.5 and close > sma50.iloc[-1]:
        return close - 2 * atr, [
            f"Closed {_rupees(close)} above 20-day high {_rupees(prior_high)}",
            f"Volume {ratio:.1f}× 20-day average",
            f"Above 50-day average {_rupees(sma50.iloc[-1])}",
        ]
    return None


def _pullback(df: pd.DataFrame, sma20, sma50, sma200, rsi, atr: float):
    close = df["close"]
    if not (close.iloc[-1] > sma200.iloc[-1] and sma50.iloc[-1] > sma200.iloc[-1]):
        return None
    if not (35 <= rsi.iloc[-1] <= 50 and rsi.iloc[-1] > rsi.iloc[-2]):
        return None
    if not close.iloc[-1] > close.iloc[-2]:
        return None
    touched = None
    for days, sma in ((20, sma20), (50, sma50)):
        for low, level in zip(df["low"].iloc[-3:], sma.iloc[-3:]):
            if level - atr <= low <= level + atr:
                touched = (days, level)
                break
        if touched:
            break
    if touched is None:
        return None
    days, level = touched
    return df["low"].iloc[-3:].min() - 0.5 * atr, [
        f"Above 200-day average {_rupees(sma200.iloc[-1])}",
        f"Dipped to the {days}-day average {_rupees(level)}",
        f"RSI {rsi.iloc[-1]:.0f}, turning up",
    ]


def find_setups(frames: dict[str, pd.DataFrame], symbols: list[str], now: datetime) -> ScanResult:
    skipped: list[Skipped] = []
    findings: list[Finding] = []
    last_dates: list[date] = []

    for symbol in symbols:
        raw = frames.get(symbol)
        if raw is None or raw.empty:
            skipped.append(Skipped(symbol=symbol, reason="no data"))
            continue
        df = _completed(raw, now)
        if len(df) < _MIN_BARS:
            skipped.append(Skipped(symbol=symbol, reason="under 200 bars"))
            continue
        last_dates.append(df.index[-1].date())

        close = df["close"]
        sma20, sma50, sma200 = (Indicators.sma(close, n) for n in (20, 50, 200))
        rsi = Indicators.rsi(close)
        atr = Indicators.atr(df["high"], df["low"], close).iloc[-1]

        setup, hit = "breakout", _breakout(df, sma50, atr)
        if hit is None:
            setup, hit = "pullback", _pullback(df, sma20, sma50, sma200, rsi, atr)
        if hit is None:
            continue

        stop, reasons = hit
        last = close.iloc[-1]
        findings.append(Finding(
            symbol=symbol,
            setup=setup,
            close=round(last, 2),
            change_pct=round((last / close.iloc[-2] - 1) * 100, 2),
            stop=round(stop, 2),
            target=round(last + 2 * (last - round(stop, 2)), 2),
            risk_pct=round((last - round(stop, 2)) / last * 100, 2),
            return_3m=round((last / close.iloc[-1 - _BARS_3M] - 1) * 100, 2),
            reasons=reasons,
        ))

    findings.sort(key=lambda f: f.return_3m, reverse=True)
    return ScanResult(
        as_of=max(last_dates) if last_dates else None,
        scanned=len(symbols),
        skipped=skipped,
        findings=findings,
    )
