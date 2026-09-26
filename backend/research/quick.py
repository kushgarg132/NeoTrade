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
import logging
from typing import Any, Dict, List

import pandas as pd
from pydantic import BaseModel

from backend.components.master.search import resolve_company_query
from backend.components.master.stock_info import fetch_stock_info_logic
from backend.components.quant.indicators import Indicators
from backend.data.providers.yfinance_provider import YFinanceProvider
from backend.database import get_database
from backend.instruments.master import InstrumentMaster
from backend.instruments.resolve import resolve_symbol

logger = logging.getLogger(__name__)

_provider = YFinanceProvider()


class QuickAnalysis(BaseModel):
    symbol: str
    company_info: Dict[str, Any]
    price_data: List[Dict[str, Any]]
    technical_analysis: Dict[str, Any]
    peers: List[str] = []


def _last(series: pd.Series):
    if series is None or len(series) == 0:
        return None
    value = series.iloc[-1]
    return float(value) if pd.notna(value) else None


def _compute_technicals(candles) -> Dict[str, Any]:
    if not candles:
        return {}

    close = pd.Series([c.close for c in candles])
    high = pd.Series([c.high for c in candles])
    low = pd.Series([c.low for c in candles])

    return {
        "rsi": _last(Indicators.rsi(close)),
        "sma_50": _last(Indicators.sma(close, 50)),
        "sma_200": _last(Indicators.sma(close, 200)),
        "atr": _last(Indicators.atr(high, low, close)),
    }


async def quick_analysis(query: str) -> QuickAnalysis:
    resolved = await resolve_company_query(query)
    symbol = resolved["symbol"]

    master = InstrumentMaster(await get_database())
    instrument = await resolve_symbol(symbol, master)

    company_info, candles = await asyncio.gather(
        fetch_stock_info_logic(symbol),
        _provider.history(instrument, interval="1d", period="1y"),
    )

    return QuickAnalysis(
        symbol=symbol,
        company_info=company_info.model_dump(mode="json"),
        price_data=[c.model_dump(mode="json") for c in candles],
        technical_analysis=_compute_technicals(candles),
        peers=resolved.get("peers", []),
    )
