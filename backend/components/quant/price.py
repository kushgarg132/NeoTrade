from fastapi import HTTPException
from typing import List
import logging

from backend.components.shared.models import PriceCandle
from backend.data.providers.yfinance_provider import YFinanceProvider
from backend.database import get_database
from backend.instruments.master import InstrumentMaster
from backend.instruments.resolve import SymbolNotFoundError, resolve_symbol

logger = logging.getLogger(__name__)

_provider = YFinanceProvider()

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
