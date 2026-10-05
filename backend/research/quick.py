"""Fast, non-AI stock snapshot: instrument resolution, quote/fundamentals,
and price-based technicals (RSI/SMA/ATR -- plain math on OHLC data, no LLM
call anywhere in this path).

This is what a stock click should render immediately. The AI-derived report
(news, sentiment, thesis -- backend.research.graph.ResearchAgent) is a
separate, slower request the frontend only fires when its own tab is opened,
since that pipeline makes several sequential LLM calls and was the actual
source of "opening a stock is slow". (A second source hid here until
2026-09-26: resolve_company_query's LLM peer lookup, ~10s, now opt-in.)
"""

import asyncio
import math
import logging
from typing import Any, Dict, List

import pandas as pd
from pydantic import BaseModel

from backend.components.master.search import resolve_company_query
from backend.components.master.stock_info import fetch_stock_info_logic
from backend.components.quant.indicators import Indicators
from backend.components.quant.support import SupportResistance
from backend.components.quant.trend import TrendDetector
from backend.data.providers.store import StoreHistoryProvider
from backend.database import get_database
from backend.instruments.master import InstrumentMaster
from backend.instruments.resolve import resolve_symbol
from backend.research.flags import stock_flags

logger = logging.getLogger(__name__)


class QuickAnalysis(BaseModel):
    symbol: str
    company_info: Dict[str, Any]
    price_data: List[Dict[str, Any]]
    technical_analysis: Dict[str, Any]
    peers: List[str] = []
    flags: List[Dict[str, Any]] = []


def _last(series: pd.Series):
    if series is None or len(series) == 0:
        return None
    value = series.iloc[-1]
    return float(value) if pd.notna(value) else None


# Trading days back for each return. "1y" spans the whole history, and only
# once it is about a year long: a 40-day-old listing has no 1-year return.
_RETURN_WINDOWS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126}
_YEAR_BARS = 240


def _finite(value):
    """A plain float, or None for NaN/inf: JSON cannot carry either."""
    value = float(value)
    return value if math.isfinite(value) else None


def _pct_change(close: pd.Series, bars: int):
    """% change over the last `bars` bars; None when the history is too short
    or the base close is 0 (a bad tick would otherwise print infinity)."""
    if len(close) <= bars:
        return None
    base, last = _finite(close.iloc[-1 - bars]), _finite(close.iloc[-1])
    return (last / base - 1) * 100 if base and last is not None else None


def _volume_ratio(volume: pd.Series):
    """Last bar's volume against the mean of the 20 bars before it."""
    if len(volume) < 21:
        return None
    mean, last = _finite(volume.iloc[-21:-1].mean()), _finite(volume.iloc[-1])
    return last / mean if mean and last is not None else None


def _levels(df: pd.DataFrame, price: float):
    try:
        support, resistance = SupportResistance.get_nearest_levels(price, SupportResistance.identify_levels(df))
        return support, resistance
    except Exception as e:  # a detector failing must not sink the snapshot
        logger.warning(f"Support/resistance failed: {e}")
        return None, None


def _trend(df: pd.DataFrame):
    try:
        return TrendDetector.detect_trend(Indicators.calculate_all(df)).value
    except Exception as e:
        logger.warning(f"Trend detection failed: {e}")
        return None


def _compute_technicals(candles) -> Dict[str, Any]:
    if not candles:
        return {}

    df = pd.DataFrame([c.model_dump() for c in candles])
    close, high, low = df["close"], df["high"], df["low"]
    price = _finite(close.iloc[-1])
    macd, macd_signal, _ = Indicators.macd(close)
    bb_upper, bb_lower = Indicators.bollinger_bands(close)
    support, resistance = _levels(df, price) if price is not None else (None, None)

    returns = {key: _pct_change(close, bars) for key, bars in _RETURN_WINDOWS.items()}
    returns["1y"] = _pct_change(close, len(close) - 1) if len(close) >= _YEAR_BARS else None

    return {
        "rsi": _last(Indicators.rsi(close)),
        "sma_50": _last(Indicators.sma(close, 50)),
        "sma_200": _last(Indicators.sma(close, 200)),
        "atr": _last(Indicators.atr(high, low, close)),
        "price": price,
        "ema_20": _last(Indicators.ema(close, 20)),
        "macd": _last(macd),
        "macd_signal": _last(macd_signal),
        "bb_upper": _last(bb_upper),
        "bb_lower": _last(bb_lower),
        "support": support,
        "resistance": resistance,
        "trend": _trend(df),
        "returns": returns,
        "volume_ratio": _volume_ratio(df["volume"]),
        "high_52w": _finite(high.max()),
        "low_52w": _finite(low.min()),
    }


async def quick_analysis(query: str) -> QuickAnalysis:
    resolved = await resolve_company_query(query)
    symbol = resolved["symbol"]

    db = await get_database()
    instrument = await resolve_symbol(symbol, InstrumentMaster(db))

    company_info, candles = await asyncio.gather(
        fetch_stock_info_logic(symbol),
        StoreHistoryProvider(db).history(instrument, interval="1d", period="1y"),
    )

    company = company_info.model_dump(mode="json")
    technicals = _compute_technicals(candles)
    return QuickAnalysis(
        symbol=symbol,
        company_info=company,
        price_data=[c.model_dump(mode="json") for c in candles],
        technical_analysis=technicals,
        peers=resolved.get("peers", []),
        flags=stock_flags(technicals, company),
    )
