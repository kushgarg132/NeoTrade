"""Ingest loops for prices: stock quotes and the macro/global board.

Quotes: `quote:{SYMBOL}` (backend/marks.py reads it). In session, held and
watched names refresh every pass (~15s) and the whole Nifty 200 every
UNIVERSE_SECONDS; outside it, everything every OFF_SESSION_SECONDS.

Macro: `macro:{yf ticker}` with the `/market/indices` row shape
({name, symbol, value, change, percent}) plus `at`, and one Mongo
`macro_series` doc per ticker per IST day holding that day's last value.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from backend.engine.autorun import in_session
from backend.engine.session import IST
from backend.marks import store_quotes

logger = logging.getLogger(__name__)

# ponytail: yfinance makes one HTTP call per ticker; Yahoo rate-limits an IP
# somewhere around a few thousand calls an hour. These cadences keep the
# full universe to ~40 calls/min in session. Move to a broker tick feed
# (plan "later" row) if fresher universe quotes are ever needed.
UNIVERSE_SECONDS = 5 * 60
OFF_SESSION_SECONDS = 10 * 60
PRIORITY_TTL_SECONDS = 120
UNIVERSE_TTL_SECONDS = 15 * 60
OFF_SESSION_TTL_SECONDS = 30 * 60

MACRO_KEY = "macro:{}"
MACRO_TTL_SECONDS = 10 * 60
MACRO = {
    "NIFTY 50": "^NSEI", "SENSEX": "^BSESN", "BANK NIFTY": "^NSEBANK", "INDIA VIX": "^INDIAVIX",
    "S&P 500": "^GSPC", "NASDAQ": "^IXIC", "FTSE 100": "^FTSE", "Nikkei 225": "^N225", "DAX": "^GDAXI",
    "Hang Seng": "^HSI", "S&P 500 futures": "ES=F", "Nasdaq futures": "NQ=F",
    "Brent crude": "BZ=F", "WTI crude": "CL=F", "Gold": "GC=F",
    "USD/INR": "INR=X", "Dollar index": "DX-Y.NYB", "US 10Y yield": "^TNX",
}

_last_universe = 0.0


def last_two(tickers: list[str]) -> dict[str, tuple[float, float]]:
    """ticker -> (last close, previous close) from one batched 5-day daily
    download. Today's daily bar moves with the session, so its close is the
    current price. Tickers with no data are left out."""
    if not tickers:
        return {}
    frame = yf.download(tickers, period="5d", interval="1d", progress=False, threads=True)["Close"]
    if isinstance(frame, pd.Series):
        frame = frame.to_frame(tickers[0])
    out = {}
    for ticker in tickers:
        if ticker not in frame:
            continue
        series = frame[ticker].dropna()
        if len(series):
            last = float(series.iloc[-1])
            out[ticker] = (last, float(series.iloc[-2]) if len(series) > 1 else last)
    return out


def _bare(symbol: str) -> str:
    return symbol.strip().upper().removesuffix(".NS").removesuffix(".BO")


async def priority_symbols(db) -> set[str]:
    """Names someone holds (paper/live ledger) or watches."""
    held = await db["paper_positions"].distinct("symbol", {"quantity": {"$ne": 0}})
    watched = await db["watchlist"].distinct("symbols")
    return {_bare(s) for s in [*held, *watched] if s}


async def _quote(redis, symbols: set[str], ttl: int) -> int:
    tickers = {f"{s}.NS": s for s in symbols}
    rows = await asyncio.to_thread(last_two, list(tickers))
    await store_quotes(redis, {tickers[t]: v for t, v in rows.items()}, ttl)
    return len(rows)


async def quotes(db, redis) -> None:
    global _last_universe
    from backend.factor.data import universe

    now = time.time()
    live = in_session(datetime.now(timezone.utc))
    priority = await priority_symbols(db)
    due = now - _last_universe >= (UNIVERSE_SECONDS if live else OFF_SESSION_SECONDS)

    if due:
        symbols = priority | {_bare(s) for s in universe()}
        n = await _quote(redis, symbols, UNIVERSE_TTL_SECONDS if live else OFF_SESSION_TTL_SECONDS)
        _last_universe = now
        logger.info("ingest quotes: %d/%d symbol(s)", n, len(symbols))
    elif live and priority:
        await _quote(redis, priority, PRIORITY_TTL_SECONDS)


async def macro(db, redis) -> None:
    rows = await asyncio.to_thread(last_two, list(MACRO.values()))
    now = datetime.now(timezone.utc)
    day = now.astimezone(IST).date().isoformat()
    async with redis.pipeline(transaction=False) as pipe:
        for name, ticker in MACRO.items():
            if ticker not in rows:
                continue
            value, prev = rows[ticker]
            change = value - prev
            pipe.set(MACRO_KEY.format(ticker), json.dumps({
                "name": name, "symbol": ticker, "value": value, "change": change,
                "percent": change / prev * 100 if prev else 0.0, "at": now.timestamp(),
            }), ex=MACRO_TTL_SECONDS)
        await pipe.execute()
    for ticker, (value, _) in rows.items():
        await db["macro_series"].update_one(
            {"_id": f"{ticker}:{day}"}, {"$set": {"ticker": ticker, "date": day, "value": value, "at": now}},
            upsert=True,
        )


async def macro_rows(redis, names_to_tickers: dict[str, str]):
    """Rows for `names_to_tickers` from the cache, in order, or None if any
    is missing (the caller then fetches itself)."""
    if redis is None:
        return None
    try:
        raws = await redis.mget([MACRO_KEY.format(t) for t in names_to_tickers.values()])
    except Exception as exc:
        logger.warning("macro cache read failed: %s", exc)
        return None
    if not all(raws):
        return None
    rows = [json.loads(r) for r in raws]
    for row, name in zip(rows, names_to_tickers):
        row.pop("at", None)
        row["name"] = name
    return rows
