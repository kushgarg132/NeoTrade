"""Daily bars and fundamentals, stored once for every reader.

Bars: Mongo `daily_bars`, one doc per (symbol, IST date) with adjusted
open/high/low/close/volume. The `bars` loop runs once a day after the close
(15:45 IST), or right away when the store has never been filled. A new
symbol gets two years; a known one the last month (cheap, and it heals a
missed day). Once a week every symbol is re-downloaded in full, because
adjusted prices shift back in time after a split or dividend. NIFTY (^NSEI)
keeps ten years for the portfolio benchmark.

Fundamentals: Mongo `fundamentals`, one doc per symbol (`_id`) holding the
FundamentalSnapshot fields plus `as_of`, refreshed once a day.

Covered symbols: the Nifty 200, the default scan list, every user's saved
scan universe, and anything held or watched. Readers
(backend/data/providers/store.py, the scanner, portfolio and analytics NIFTY
series) fall back to yfinance for anything missing or stale.
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional

import pandas as pd
import yfinance as yf

from backend.engine.session import IST

logger = logging.getLogger(__name__)

BARS = "daily_bars"
FUNDAMENTALS = "fundamentals"
NIFTY = "^NSEI"
AFTER_CLOSE = time(15, 45)
STALE_DAYS = 4  # newest bar older than this = stale (a weekend plus one holiday)
FUNDAMENTALS_MAX_AGE = timedelta(days=3)
FULL_EVERY = timedelta(days=7)
BARS_AS_OF_KEY = "bars:as_of"  # IST date of the last finished daily pass
BARS_FULL_KEY = "bars:full_at"  # IST date of the last full re-download
FUNDAMENTALS_AS_OF_KEY = "fundamentals:as_of"
_FUNDAMENTALS_CONCURRENCY = 4


def today_ist(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(IST).date()


def ticker(symbol: str) -> str:
    return symbol if symbol.startswith("^") else f"{symbol}.NS"


async def ensure_indexes(db) -> None:
    await db[BARS].create_index([("symbol", 1), ("date", 1)], unique=True)


async def symbols(db) -> set[str]:
    from backend.components.quant.indian_stocks import ALL_SCAN_STOCKS
    from backend.datalayer.prices import _bare, priority_symbols
    from backend.factor.data import universe

    saved = await db["user_prefs"].distinct("universe")
    return {_bare(s) for s in [*universe(), *ALL_SCAN_STOCKS, *saved] if s} | await priority_symbols(db)


# --- store ---------------------------------------------------------------

def _download(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    """ticker -> frame with lower-case ohlcv columns, from one batched call."""
    if not tickers:
        return {}
    raw = yf.download(
        tickers, period=period, interval="1d", group_by="ticker",
        auto_adjust=True, threads=True, progress=False,
    )
    frames = {}
    for t in tickers:
        if isinstance(raw.columns, pd.MultiIndex):
            if t not in raw.columns.get_level_values(0):
                continue
            df = raw[t]
        elif len(tickers) == 1:
            df = raw
        else:
            continue
        df = df.rename(columns=str.lower).dropna(subset=["close"])
        if not df.empty:
            frames[t] = df
    return frames


async def write(db, symbol: str, df: pd.DataFrame) -> int:
    """Replaces the symbol's bars over the frame's date range. Delete then
    insert, not bulk upserts: two round trips per symbol, and pymongo's
    UpdateOne doesn't run on the mongomock fake (see instruments/master.py).
    A reader landing between the two misses the symbol and falls back."""
    docs = [
        {
            "symbol": symbol, "date": index.strftime("%Y-%m-%d"),
            "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]),
            "close": float(row["close"]), "volume": float(row.get("volume") or 0),
        }
        for index, row in df.iterrows()
    ]
    if docs:
        await db[BARS].delete_many({"symbol": symbol, "date": {"$gte": docs[0]["date"]}})
        await db[BARS].insert_many(docs, ordered=False)
    return len(docs)


async def read(
    db, symbols: Iterable[str], since: date, today: Optional[date] = None,
) -> dict[str, pd.DataFrame]:
    """symbol -> frame (DatetimeIndex of dates, ohlcv columns) from `since`.
    A symbol whose newest bar is older than STALE_DAYS is left out."""
    wanted = list(symbols)
    if not wanted:
        return {}
    rows: dict[str, list] = {}
    cursor = db[BARS].find(
        {"symbol": {"$in": wanted}, "date": {"$gte": since.isoformat()}}, {"_id": 0},
    ).sort("date", 1)
    async for doc in cursor:
        rows.setdefault(doc.pop("symbol"), []).append(doc)
    cutoff = ((today or today_ist()) - timedelta(days=STALE_DAYS)).isoformat()
    frames = {}
    for symbol, docs in rows.items():
        if docs[-1]["date"] < cutoff:
            continue
        df = pd.DataFrame(docs)
        df.index = pd.to_datetime(df.pop("date"))
        frames[symbol] = df
    return frames


async def nifty_closes(db, since: date) -> list[tuple[date, float]]:
    frame = (await read(db, [NIFTY], since)).get(NIFTY)
    if frame is None:
        return []
    return [(index.date(), float(close)) for index, close in frame["close"].items()]


# --- ingest loops ----------------------------------------------------------

def _due(as_of: Optional[str], now: datetime) -> bool:
    if as_of is None:
        return True  # never filled: fill now, whatever the time
    local = now.astimezone(IST)
    return as_of < local.date().isoformat() and local.time() >= AFTER_CLOSE


async def loop(db, redis, now: Optional[datetime] = None) -> None:
    now = now or datetime.now(timezone.utc)
    if not _due(await redis.get(BARS_AS_OF_KEY), now):
        return
    await ensure_indexes(db)
    today = today_ist(now)
    full_at = await redis.get(BARS_FULL_KEY)
    full = full_at is None or date.fromisoformat(full_at) <= today - FULL_EVERY
    known = set() if full else set(await db[BARS].distinct("symbol"))

    wanted = await symbols(db)
    batches = [
        ("2y", [ticker(s) for s in wanted if s not in known]),
        ("1mo", [ticker(s) for s in wanted if s in known]),
        ("1mo" if NIFTY in known else "10y", [NIFTY]),
    ]
    written = stored = 0
    for period, tickers in batches:
        frames = await asyncio.to_thread(_download, tickers, period)
        for t, df in frames.items():
            written += await write(db, t.removesuffix(".NS"), df)
            stored += 1
    if not stored:
        raise RuntimeError(f"bars: no data for any of {len(wanted)} symbol(s)")  # retry next pass
    await redis.set(BARS_AS_OF_KEY, today.isoformat())
    if full:
        await redis.set(BARS_FULL_KEY, today.isoformat())
    logger.info("ingest bars: %d symbol(s), %d bar(s)%s", stored, written, " (full)" if full else "")


async def fundamentals_loop(db, redis, now: Optional[datetime] = None) -> None:
    from backend.screening.providers.yfinance_fundamentals import YFinanceFundamentalsProvider

    now = now or datetime.now(timezone.utc)
    today = today_ist(now).isoformat()
    if await redis.get(FUNDAMENTALS_AS_OF_KEY) == today:
        return
    from backend.instruments.master import InstrumentMaster

    master = InstrumentMaster(db)
    provider = YFinanceFundamentalsProvider()
    semaphore = asyncio.Semaphore(_FUNDAMENTALS_CONCURRENCY)

    async def one(symbol: str) -> bool:
        async with semaphore:
            instrument = await master.get("NSE", symbol)
            snapshot = instrument and await provider.snapshot(instrument)
        if not snapshot:
            return False
        await db[FUNDAMENTALS].replace_one(
            {"_id": symbol}, {**snapshot.model_dump(), "as_of": now}, upsert=True,
        )
        return True

    wanted = await symbols(db)
    stored = sum(await asyncio.gather(*(one(s) for s in wanted)))
    if not stored:
        raise RuntimeError(f"fundamentals: none of {len(wanted)} symbol(s) fetched")
    await redis.set(FUNDAMENTALS_AS_OF_KEY, today)
    logger.info("ingest fundamentals: %d/%d symbol(s)", stored, len(wanted))
