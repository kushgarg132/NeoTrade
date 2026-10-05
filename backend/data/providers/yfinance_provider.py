import asyncio
import logging
from datetime import datetime

import pandas as pd
import yfinance as yf

from backend.components.shared.models import PriceCandle
from backend.instruments.models import Instrument

logger = logging.getLogger(__name__)

_EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}


class YFinanceProvider:
    """MarketDataProvider backed by yfinance. Takes an already-resolved
    Instrument and derives the yfinance ticker deterministically -- no more
    trying [".NS", ".BO", ""] suffixes and hoping one sticks."""

    def _ticker_symbol(self, instrument: Instrument) -> str:
        suffix = _EXCHANGE_SUFFIX.get(instrument.exchange)
        if suffix is None:
            raise ValueError(f"Unsupported exchange for yfinance: {instrument.exchange!r}")
        return f"{instrument.tradingsymbol}{suffix}"

    async def history(self, instrument: Instrument, interval: str, period: str) -> list[PriceCandle]:
        ticker_symbol = self._ticker_symbol(instrument)
        logger.info(f"Fetching price history for {ticker_symbol}, period: {period}, interval: {interval}")

        # yfinance is a blocking HTTP client; calling it straight from an
        # async def runs it on the one event loop this (single-worker)
        # process has, freezing every other in-flight request for as long as
        # the fetch takes. to_thread moves it off the loop.
        df = await asyncio.to_thread(lambda: yf.Ticker(ticker_symbol).history(period=period, interval=interval))

        if df.empty:
            raise ValueError(f"No price data found for {ticker_symbol}")

        candles = []
        for index, row in df.iterrows():
            if isinstance(index, datetime):
                ts = index
            elif hasattr(index, "to_pydatetime"):
                ts = index.to_pydatetime()
            else:
                ts = pd.to_datetime(index)

            candles.append(PriceCandle(
                symbol=ticker_symbol.upper(),
                timestamp=ts,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                adj_close=float(row.get("Adj Close", row["Close"])),
                volume=int(row.get("Volume", 0)),
            ))

        logger.info(f"Retrieved {len(candles)} candles for {ticker_symbol}")
        return candles

    async def quote(self, instrument: Instrument) -> dict:
        """Last price, ohlc, volume -- cheap enough to build from a short
        history pull rather than a separate .info network call."""
        ticker_symbol = self._ticker_symbol(instrument)
        df = await asyncio.to_thread(lambda: yf.Ticker(ticker_symbol).history(period="5d", interval="1d"))
        # After IST midnight yfinance adds the new day's row with NaN prices
        # (volume only) until it trades; the last real close is the quote.
        df = df.dropna(subset=["Close"])

        if df.empty:
            raise ValueError(f"No quote data found for {ticker_symbol}")

        last = df.iloc[-1]
        return {
            "symbol": ticker_symbol.upper(),
            "last_price": float(last["Close"]),
            "open": float(last["Open"]),
            "high": float(last["High"]),
            "low": float(last["Low"]),
            "close": float(last["Close"]),
            "volume": int(last.get("Volume", 0)),
        }

    async def info(self, instrument: Instrument) -> dict:
        """Raw yfinance `.info` dict (falling back to a short history pull
        when `.info` comes back empty, same as the old suffix-loop code did)
        for callers that need company fundamentals, not just OHLCV."""
        ticker_symbol = self._ticker_symbol(instrument)
        ticker = yf.Ticker(ticker_symbol)
        info = await asyncio.to_thread(lambda: ticker.info)

        current_price_val = info.get("regularMarketPrice") or info.get("currentPrice")
        if info and current_price_val is not None:
            return {**info, "_ticker_symbol": ticker_symbol}

        hist = await asyncio.to_thread(lambda: ticker.history(period="5d"))
        if hist.empty:
            raise ValueError(f"No stock info found for {ticker_symbol}")

        current_price = float(hist["Close"].iloc[-1])
        previous_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current_price
        return {
            "_ticker_symbol": ticker_symbol,
            "_from_history_fallback": True,
            "regularMarketPrice": current_price,
            "previousClose": previous_close,
            "regularMarketVolume": float(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else None,
        }
