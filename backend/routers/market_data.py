from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import yfinance as yf
import logging
import asyncio

from backend.market_cache import cached

router = APIRouter()
logger = logging.getLogger(__name__)

# Indices to track
INDICES = {
    "NIFTY 50": "^NSEI",
    "SENSEX": "^BSESN",
    "BANK NIFTY": "^NSEBANK",
    "INDIA VIX": "^INDIAVIX" # Might need verification, fallback to ^VIX if fails?
}


# NIFTY 50 Symbols
def _fetch_ticker_data_sync(symbol: str, name: str) -> Dict[str, Any]:
    ticker = yf.Ticker(symbol)

    # fast_info can raise (some symbols lack a currentTradingPeriod) instead
    # of just returning None, so the history() fallback has to be reachable
    # on exception too, not only on a None price.
    price = prev_close = None
    try:
        price = ticker.fast_info.last_price
        prev_close = ticker.fast_info.previous_close
    except Exception:
        pass

    if price is None or prev_close is None:
        hist = ticker.history(period="2d")
        if len(hist) >= 1:
            price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else price

    if price is None:
        return None

    change = price - prev_close
    percent = (change / prev_close) * 100

    return {
        "name": name,
        "symbol": symbol,
        "value": price,
        "change": change,
        "percent": percent
    }


async def fetch_ticker_data(symbol: str, name: str) -> Dict[str, Any]:
    # yfinance is a synchronous/blocking HTTP client. Called directly inside
    # an async def, asyncio.gather() over these does NOT run them
    # concurrently -- each call blocks the single event loop in turn, which
    # on this single-worker uvicorn process stalls every other in-flight
    # request (other API calls, the websocket) for as long as this endpoint's
    # symbol list takes to fetch serially. to_thread moves the blocking work
    # off the loop so gather() actually parallelizes it.
    try:
        return await asyncio.to_thread(_fetch_ticker_data_sync, symbol, name)
    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        return None

NIFTY_50_SYMBOLS = [
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "BPCL.NS", "BHARTIARTL.NS",
    "BRITANNIA.NS", "CIPLA.NS", "COALINDIA.NS", "DIVISLAB.NS", "DRREDDY.NS",
    "EICHERMOT.NS", "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS",
    "HEROMOTOCO.NS", "HINDALCO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "ITC.NS",
    "INDUSINDBK.NS", "INFY.NS", "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS",
    "M&M.NS", "MARUTI.NS", "NTPC.NS", "NESTLEIND.NS", "ONGC.NS",
    "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS", "SBIN.NS", "SUNPHARMA.NS",
    "TCS.NS", "TATACONSUM.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "TECHM.NS",
    "TITAN.NS", "ULTRACEMCO.NS", "UPL.NS", "WIPRO.NS"
]

# How long a feed is fresh; older ones are still served while a refresh
# runs (backend/market_cache.py).
QUOTES_TTL = 60
MOVERS_TTL = 5 * 60


def _movers_sync() -> List[Dict[str, Any]]:
    """The six NIFTY 50 stocks that moved most today, from one batched
    download of every constituent's last few daily closes -- 49 separate
    quote calls took most of the home page's load time."""
    closes = yf.download(NIFTY_50_SYMBOLS, period="5d", interval="1d", progress=False, threads=True)["Close"]
    movers = []
    for symbol in NIFTY_50_SYMBOLS:
        if symbol not in closes:
            continue
        series = closes[symbol].dropna()
        if len(series) < 2:
            continue
        price, prev = float(series.iloc[-1]), float(series.iloc[-2])
        movers.append({"name": symbol, "symbol": symbol, "value": price, "change": price - prev,
                       "percent": (price - prev) / prev * 100 if prev else 0.0})
    movers.sort(key=lambda m: abs(m["percent"]), reverse=True)
    return movers[:6]


async def _quotes(names_to_symbols: Dict[str, str]) -> List[Dict[str, Any]]:
    results = await asyncio.gather(*(fetch_ticker_data(sym, name) for name, sym in names_to_symbols.items()))
    return [r for r in results if r is not None]


@router.get("/market/indices")
async def get_market_indices():
    return await cached("indices", QUOTES_TTL, lambda: _quotes(INDICES))


@router.get("/market/trending")
async def get_trending_stocks():
    return await cached("movers", MOVERS_TTL, lambda: asyncio.to_thread(_movers_sync))


# Global Indices
GLOBAL_INDICES = {
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "FTSE 100": "^FTSE",
    "Nikkei 225": "^N225",
    "DAX": "^GDAXI",
}

@router.get("/market/global")
async def get_global_indices():
    """Fetch global market indices."""
    return await cached("global", QUOTES_TTL, lambda: _quotes(GLOBAL_INDICES))



# ---------------------------------------------------------------------------
# One index, in detail: what a tap on an index row opens. Only the tickers
# this module already lists are accepted, so the route is not a general
# Yahoo proxy.
# ---------------------------------------------------------------------------

def _known_index_names() -> Dict[str, str]:
    return {ticker: name for name, ticker in {**INDICES, **GLOBAL_INDICES}.items()}


def _mean_of_last(closes: List[float], window: int):
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _fetch_index_detail_sync(ticker: str, name: str) -> Dict[str, Any] | None:
    hist = yf.Ticker(ticker).history(period="1y", interval="1d")
    if hist is None or hist.empty:
        return None

    points = [
        {"date": index.strftime("%Y-%m-%d"), "close": float(row["Close"])}
        for index, row in hist.iterrows()
    ]
    closes = [point["close"] for point in points]
    value = closes[-1]
    previous = closes[-2] if len(closes) > 1 else value
    change = value - previous

    return {
        "name": name,
        "symbol": ticker,
        "value": value,
        "change": change,
        "percent": (change / previous) * 100 if previous else 0.0,
        "high_52w": max(closes),
        "low_52w": min(closes),
        "sma_50": _mean_of_last(closes, 50),
        "sma_200": _mean_of_last(closes, 200),
        "points": points,
    }


@router.get("/market/index/{ticker}")
async def get_index_detail(ticker: str):
    """A year of daily closes plus the figures a reader checks on an index:
    level, day change, 52-week range and the 50/200-day averages."""
    name = _known_index_names().get(ticker)
    if name is None:
        raise HTTPException(status_code=404, detail=f"{ticker} is not a tracked index")
    try:
        detail = await asyncio.to_thread(_fetch_index_detail_sync, ticker, name)
    except Exception as e:
        logger.error(f"Error fetching index detail for {ticker}: {e}")
        detail = None
    if detail is None:
        raise HTTPException(status_code=502, detail=f"No price data for {name} right now")
    return detail


@router.get("/market/index/{ticker}/analysis")
async def get_index_analysis(ticker: str):
    """AI-written explanation of why this index moved in its latest session,
    with the session figures and headlines it was written from. Explains the
    past only -- no forecasts, no calls."""
    from backend.research.index_move import ExplanationUnavailable, explain_index_move

    name = _known_index_names().get(ticker)
    if name is None:
        raise HTTPException(status_code=404, detail=f"{ticker} is not a tracked index")
    try:
        return await explain_index_move(ticker, name)
    except ExplanationUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
