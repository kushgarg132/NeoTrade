from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
import logging

from backend.components.shared.models import PriceCandle
from backend.data.providers.yfinance_provider import YFinanceProvider
from backend.database import get_database
from backend.instruments.master import InstrumentMaster
from backend.instruments.resolve import SymbolNotFoundError, resolve_symbol

logger = logging.getLogger(__name__)

router = APIRouter()

_provider = YFinanceProvider()

class PriceHistoryRequest(BaseModel):
    symbol: str
    period: str = "1mo" # 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
    interval: str = "1d" # 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo

class PriceHistoryResponse(BaseModel):
    symbol: str
    candles: List[PriceCandle]
    source: str = "yfinance"  # Track data source

@router.post("/price_history", response_model=PriceHistoryResponse)
async def fetch_price_history(request: PriceHistoryRequest):
    """
    Fetches historical price data for a given symbol.
    Resolves the symbol against the instrument master, then fetches via
    YFinanceProvider using the exact, deterministic NSE/BSE ticker.
    """
    candles, source = await fetch_price_history_logic(request.symbol, request.period, request.interval)
    return PriceHistoryResponse(symbol=request.symbol, candles=candles, source=source)

async def fetch_price_history_logic(symbol: str, period: str = "1mo", interval: str = "1d") -> tuple[List[PriceCandle], str]:
    """
    Core logic for fetching price history: resolve `symbol` to an exact
    instrument, then fetch via YFinanceProvider. No suffix guessing.
    """
    logger.info(f"Fetching price history for {symbol}, period: {period}, interval: {interval}")

    master = InstrumentMaster(await get_database())
    try:
        instrument = await resolve_symbol(symbol, master)
    except SymbolNotFoundError as e:
        logger.error(f"Failed to resolve symbol {symbol}: {e}")
        raise HTTPException(status_code=404, detail=f"No data found for symbol {symbol}: {e}")

    try:
        candles = await _provider.history(instrument, interval=interval, period=period)
    except ValueError as e:
        logger.error(f"Failed to fetch price history for {symbol} ({instrument.tradingsymbol}): {e}")
        raise HTTPException(status_code=404, detail=str(e))

    logger.info(f"Price history fetch complete for {instrument.tradingsymbol}. Returning {len(candles)} candles")
    return candles, "yfinance"
