"""Inputs for the factor strategy: the Nifty 200 members (bundled CSV from
NSE, today's list -- see the survivorship note in backtest.py) and their
adjusted daily closes from yfinance, cached on disk for a day."""

import csv
import logging
import os
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

UNIVERSE_FILE = Path(__file__).with_name("nifty200.csv")
CACHE_DIR = Path(os.environ.get("FACTOR_CACHE_DIR", "/tmp/neotrade-factor"))
CACHE_SECONDS = 20 * 60 * 60
MARKET = "^NSEI"            # trend filter
# Price indices (no dividends: understate total return by ~1.3%/yr).
# NIFTYBEES is not used: yfinance's adjusted series has an unadjusted
# split (237% vol, -90% "drawdown").
BENCHMARKS = {"Nifty 50": "^NSEI", "Nifty 200": "^CNX200"}
RISK_OFF_ETF = "LIQUIDBEES"


def universe() -> list[str]:
    with UNIVERSE_FILE.open() as f:
        return [row["Symbol"].strip() for row in csv.DictReader(f) if row.get("Series", "EQ").strip() == "EQ"]


def _download(tickers: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf

    frame = yf.download(tickers, start=start, progress=False, auto_adjust=True, threads=True)["Close"]
    return frame.to_frame(tickers[0]) if isinstance(frame, pd.Series) else frame


def closes(symbols: list[str], start: str = "2008-01-01") -> pd.DataFrame:
    """Adjusted closes, one column per NSE symbol (no .NS suffix)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"closes-{start}-{abs(hash(tuple(sorted(symbols))))}.pkl"
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_SECONDS:
        return pd.read_pickle(path)
    frame = _download([f"{s}.NS" for s in symbols], start)
    frame.columns = [c.removesuffix(".NS") for c in frame.columns]
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None)
    frame.to_pickle(path)
    return frame


def series(ticker: str, start: str = "2008-01-01") -> pd.Series:
    frame = _download([ticker], start)
    s = frame.iloc[:, 0].dropna()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None)
    return s
