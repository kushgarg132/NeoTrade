from langchain_core.tools import tool
from typing import List, Optional
import logging

# Import logic from existing components
from backend.components.master.stock_info import fetch_stock_info_logic
from backend.components.quant.price import fetch_price_history_logic
from backend.components.master.search import resolve_company_query

logger = logging.getLogger(__name__)

@tool
async def fetch_stock_info_tool(symbol: str) -> str:
    """
    Fetches comprehensive information about a specific company/stock.
    Includes: Current price, PE ratio, Market Cap, Sector, Industry, 52-week highs/lows, etc.
    Useful when asked for 'details', 'fundamentals', or 'info' about a stock.
    """
    try:
        info = await fetch_stock_info_logic(symbol)
        
        # Format as a readable string for the LLM
        return f"""
        Stock Info for {info.symbol} ({info.name}):
        - Current Price: {info.currency} {info.current_price}
        - Day Change: {info.day_change:.2f} ({info.day_change_percent:.2f}%)
        - Sector: {info.sector}
        - Industry: {info.industry}
        - Market Cap: {info.market_cap}
        - 52W High/Low: {info.week_52_high} / {info.week_52_low}
        - PE Ratio: {info.pe_ratio}
        - Dividend Yield: {f'{info.dividend_yield * 100:.2f}%' if info.dividend_yield is not None else 'n/a'}
        """
    except Exception as e:
        logger.error(f"Error in fetch_stock_info_tool: {e}")
        return f"Failed to fetch stock info: {str(e)}"

@tool
async def fetch_price_history_tool(symbol: str, period: str = "1mo") -> str:
    """
    Fetches historical price data (candles) for a stock.
    Useful for technical analysis, analyzing trends, or finding past prices.
    Period options: 1d, 5d, 1mo, 3mo, 6mo, 1y, ytd.
    """
    try:
        candles, source = await fetch_price_history_logic(symbol, period=period)
        
        if not candles:
            return f"No price history found for {symbol}."
            
        # Summarize the data for the LLM to avoid context overflow
        # If it's a lot of data, just give the summary + last few days
        
        summary = f"Retrieved {len(candles)} candles from {source}. Summary:\n"
        summary += f"Start: {candles[0].timestamp.strftime('%Y-%m-%d')} - Close: {candles[0].close}\n"
        summary += f"End: {candles[-1].timestamp.strftime('%Y-%m-%d')} - Close: {candles[-1].close}\n"
        
        summary += "\nLast 5 data points:\n"
        for c in candles[-5:]:
           summary += f"{c.timestamp.strftime('%Y-%m-%d')}: Open={c.open}, Close={c.close}, High={c.high}, Low={c.low}, Vol={c.volume}\n"
           
        return summary
    except Exception as e:
        logger.error(f"Error in fetch_price_history_tool: {e}")
        return f"Failed to fetch price history: {str(e)}"

@tool
async def resolve_symbol_tool(query: str) -> str:
    """
    Helps identify the correct stock symbol for a company name.
    Useful if the user asks for 'Tata Motors' and you need to know it's 'TMPV.NS'.
    """
    try:
        data = await resolve_company_query(query, with_peers=True)
        symbol = data.get("symbol")
        name = data.get("name")
        peers = data.get("peers", [])
        
        if symbol == "UNKNOWN":
             return f"Could not resolve symbol for '{query}'."
             
        return f"Found symbol for '{query}': {symbol} ({name}). Peers: {', '.join(peers)}"

    except Exception as e:
        logger.error(f"Error in resolve_symbol_tool: {e}")
        return f"Failed to resolve symbol: {str(e)}"
