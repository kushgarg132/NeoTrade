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
from typing import Optional

import pandas as pd
import yfinance as yf

from backend.engine.autorun import in_session
from backend.engine.session import IST
from backend.marks import store_quotes

logger = logging.getLogger(__name__)

# In session the admin's broker session prices every name each pass when it can (`_broker_quotes`).
# Yahoo covers the rest and every name off session. It makes one HTTP call per ticker and rate-limits
# an IP at a few thousand calls an hour, so these cadences keep the universe to ~40 calls/min.
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


def _closes(frame, tickers: list[str]):
    frame = frame["Close"]
    return frame.to_frame(tickers[0]) if isinstance(frame, pd.Series) else frame


def _latest_bars(tickers: list[str]) -> dict:
    """ticker -> (session date, last price, (previous session's date, its last price) or None) from 5-minute bars;
    {} when they fail, so the daily figures stand."""
    try:
        frame = yf.download(tickers, period="2d", interval="5m", progress=False, threads=True, ignore_tz=True)
        if "Close" not in frame:
            return {}
        bars = _closes(frame, tickers)
        out = {}
        for ticker in tickers:
            series = bars[ticker].dropna() if ticker in bars else []
            if len(series):
                day = series.index[-1].date()
                earlier = series[series.index.date < day]
                prior = (earlier.index[-1].date(), float(earlier.iloc[-1])) if len(earlier) else None
                out[ticker] = (day, float(series.iloc[-1]), prior)
        return out
    except Exception as exc:
        logger.warning("intraday quotes failed: %s", exc)
        return {}


def last_two(tickers: list[str]) -> dict[str, tuple[float, float]]:
    """ticker -> (last price, previous session's close). Yahoo's daily bar can miss a whole finished session, for
    stocks and indices alike (Monday evening its last close was Friday's; Tuesday noon 45 of the Nifty 200 still had
    no Monday bar), so the price comes from 5-minute bars and the previous close from the last daily bar before that
    session, or from that session's last 5-minute bar when the daily bars have not got there. Once a session is
    over its own daily close, the official one, beats its last trade. Tickers with no data are left out."""
    if not tickers:
        return {}
    # auto_adjust off: on an ex-dividend day the adjusted close takes the dividend out of yesterday, and the day move
    # stops matching the broker's (INFY 3 Nov: -2.1% on the broker, +0.1% adjusted). Close stays split-adjusted.
    frame = yf.download(tickers, period="5d", interval="1d", progress=False, threads=True, auto_adjust=False)
    if "Close" not in frame:  # an outage returns an empty frame
        return {}
    daily = _closes(frame, tickers)
    latest = _latest_bars(tickers)
    now = datetime.now(timezone.utc)
    today, live = now.astimezone(IST).date(), in_session(now)
    out = {}
    for ticker in tickers:
        if ticker not in daily:
            continue
        series = daily[ticker].dropna()
        if ticker in latest:
            day, price, prior = latest[ticker]
            own = series[series.index.date == day]
            if len(own) and not (day == today and live):
                price = float(own.iloc[-1])
            before = series[series.index.date < day]
            if prior and (not len(before) or before.index[-1].date() < prior[0]):
                out[ticker] = (price, prior[1])
                continue
            if len(before):
                out[ticker] = (price, float(before.iloc[-1]))
                continue
        if len(series):
            last = float(series.iloc[-1])
            out[ticker] = (last, float(series.iloc[-2]) if len(series) > 1 else last)
    return out


def _bare(symbol: str) -> str:
    return symbol.strip().upper().removesuffix(".NS").removesuffix(".BO")


async def priority_symbols(db) -> set[str]:
    """Names someone holds -- in a paper or live ledger, or really, in the
    latest portfolio read of each user's brokers -- or watches. A real
    holding outside every scan list (CPPLUS, JINDALSAW) had no stored bars,
    so its day move was measured from a days-old close."""
    held = await db["paper_positions"].distinct("symbol", {"quantity": {"$ne": 0}})
    watched = await db["watchlist"].distinct("symbols")
    real = []
    for user_id in await db["portfolio_snapshots"].distinct("user_id"):
        latest = await db["portfolio_snapshots"].find_one(
            {"user_id": user_id}, {"raw_holdings.symbol": 1, "raw_holdings.kind": 1}, sort=[("at", -1)])
        real += [h["symbol"] for h in (latest or {}).get("raw_holdings") or [] if h.get("kind", "STOCK") != "MF"]
    return {_bare(s) for s in [*held, *watched, *real] if s}


async def open_pick_symbols(db) -> set[str]:
    """Names on the Picks list, some of them outside the Nifty 200 scan list."""
    today = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
    return {_bare(s) for s in await db["picks"].distinct("symbol", {"due_date": {"$gt": today}})}


async def _quote(redis, symbols: set[str], ttl: int) -> int:
    tickers = {f"{s}.NS": s for s in symbols}
    rows = await asyncio.to_thread(last_two, list(tickers))
    await store_quotes(redis, {tickers[t]: v for t, v in rows.items()}, ttl)
    return len(rows)


async def _broker_quotes(db, redis, symbols: set[str]) -> dict[str, tuple[float, Optional[float]]]:
    """Live prices from the admin's broker when it has a batch call and a session. {} sends them all to Yahoo."""
    from backend.datalayer.bars import _broker_session

    try:
        _, adapter = await _broker_session(db, redis)
        batch = getattr(adapter, "batch_quotes", None)
        return await batch(sorted(symbols)) if batch else {}
    except Exception as exc:
        logger.warning("broker quotes failed, Yahoo takes over: %s", exc)
        return {}


async def quotes(db, redis) -> None:
    global _last_universe
    from backend.factor.data import universe

    now = time.time()
    live = in_session(datetime.now(timezone.utc))
    priority = await priority_symbols(db)
    due = now - _last_universe >= (UNIVERSE_SECONDS if live else OFF_SESSION_SECONDS)

    wanted = priority | {_bare(s) for s in universe()} | await open_pick_symbols(db)
    # The long TTL: if the session dies mid-day, quotes must outlast the wait for Yahoo's next pass.
    broker = await _broker_quotes(db, redis, wanted) if live else {}
    await store_quotes(redis, broker, UNIVERSE_TTL_SECONDS)

    if due:
        symbols = wanted - set(broker)
        _last_universe = now  # stamped before the download so an outage waits a cadence, not 15 s
        n = await _quote(redis, symbols, UNIVERSE_TTL_SECONDS if live else OFF_SESSION_TTL_SECONDS) if symbols else 0
        logger.info("ingest quotes: %d from the broker, %d/%d from Yahoo", len(broker), n, len(symbols))
    elif live and priority - set(broker):
        await _quote(redis, priority - set(broker), PRIORITY_TTL_SECONDS)


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


async def macro_rows(redis, names_to_tickers: dict[str, str]) -> list[dict]:
    """The cached rows for `names_to_tickers`, in order, each with `at` (epoch
    seconds it was fetched). Missing tickers are left out: the caller fetches
    only those (one dead ticker used to send every call down the slow path)."""
    if redis is None:
        return []
    try:
        raws = await redis.mget([MACRO_KEY.format(t) for t in names_to_tickers.values()])
    except Exception as exc:
        logger.warning("macro cache read failed: %s", exc)
        return []
    rows = []
    for raw, name in zip(raws, names_to_tickers):
        if raw:
            rows.append({**json.loads(raw), "name": name})
    return rows
