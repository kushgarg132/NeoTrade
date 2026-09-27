"""Fetches everything the portfolio scorecard needs and stores the result.

Holdings come from each of the user's connected brokers; buy dates from
their journal; NIFTY history, sectors and a year of daily closes from
yfinance. Each run is saved to `portfolio_snapshots` (per user_id), so a
later run can say what changed.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import yfinance as yf

from backend.brokers.protocol import BrokerSessionState
from backend.brokers.registry import BROKERS, get_broker_adapter
from backend.journal.store import JournalStore
from backend.portfolio.scorecard import build_scorecard

logger = logging.getLogger(__name__)

SECTOR_TTL = timedelta(days=30)
_NIFTY: dict = {"at": 0.0, "points": []}
NIFTY_CACHE_SECONDS = 60 * 60


def _ticker(symbol: str, exchange: str | None) -> str:
    return f"{symbol}.BO" if exchange == "BSE" else f"{symbol}.NS"


def _nifty_sync() -> list:
    # Ten years: the benchmark needs NIFTY's close on the day of the oldest
    # journal buy still held.
    hist = yf.Ticker("^NSEI").history(period="10y", interval="1d")
    return [(index.date(), float(row["Close"])) for index, row in hist.iterrows()]


async def _nifty() -> list:
    if not _NIFTY["points"] or time.time() - _NIFTY["at"] > NIFTY_CACHE_SECONDS:
        try:
            _NIFTY.update(at=time.time(), points=await asyncio.to_thread(_nifty_sync))
        except Exception as exc:
            logger.warning("portfolio: NIFTY history unavailable: %s", exc)
    return _NIFTY["points"]


def _sector_sync(ticker: str):
    return (yf.Ticker(ticker).info or {}).get("sector")


async def _sectors(db, stocks: list[tuple[str, str | None]]) -> dict:
    """Sector per stock symbol, cached in `instrument_sectors` for a month
    (shared reference data, not per user). None when yfinance has none."""
    cache = db["instrument_sectors"]
    now = datetime.now(timezone.utc)
    known = {
        d["_id"]: d.get("sector")
        for d in await cache.find({"_id": {"$in": [s for s, _ in stocks]}}).to_list(length=None)
        if d["at"].replace(tzinfo=timezone.utc) > now - SECTOR_TTL
    }
    for symbol, exchange in stocks:
        if symbol in known:
            continue
        try:
            known[symbol] = await asyncio.to_thread(_sector_sync, _ticker(symbol, exchange))
        except Exception as exc:
            logger.warning("portfolio: no sector for %s: %s", symbol, exc)
            known[symbol] = None
        await cache.update_one({"_id": symbol}, {"$set": {"sector": known[symbol], "at": now}}, upsert=True)
    return known


def _daily_returns_sync(tickers: dict[str, str]) -> dict:
    if len(tickers) < 2:
        return {}
    closes = yf.download(list(tickers.values()), period="1y", interval="1d", progress=False)["Close"]
    returns = closes.pct_change()
    result = {}
    for symbol, ticker in tickers.items():
        if ticker in returns:
            series = returns[ticker].dropna()
            result[symbol] = {index.date(): float(value) for index, value in series.items()}
    return result


async def fetch_holdings(user_id: str, credentials, redis) -> tuple[list, dict]:
    """Holdings from every broker with an ACTIVE session, and the error per
    broker that failed (one broker down must not hide the others)."""
    holdings, errors = [], {}
    for broker in BROKERS:
        adapter = await get_broker_adapter(broker, user_id, credentials, redis)
        if await adapter.state() != BrokerSessionState.ACTIVE:
            continue
        try:
            holdings += await adapter.get_holdings()
        except Exception as exc:
            logger.warning("portfolio: %s holdings failed for %s: %s", broker, user_id, exc)
            errors[broker] = str(exc)
    return holdings, errors


async def refresh_portfolio(db, user_id: str, credentials, redis) -> dict:
    holdings, errors = await fetch_holdings(user_id, credentials, redis)
    stocks = sorted({(h.symbol, h.exchange) for h in holdings if h.kind == "STOCK"})
    trades = await JournalStore(db).list_trades(user_id)
    try:
        returns = await asyncio.to_thread(_daily_returns_sync, {s: _ticker(s, e) for s, e in stocks})
    except Exception as exc:
        logger.warning("portfolio: daily closes unavailable: %s", exc)
        returns = {}

    card = build_scorecard(holdings, trades, await _nifty(), await _sectors(db, stocks), returns)
    snapshot = {
        "user_id": user_id, "at": datetime.now(timezone.utc), "errors": errors,
        "brokers": sorted({h.broker for h in holdings}), **card,
    }
    await db["portfolio_snapshots"].insert_one(dict(snapshot))
    return snapshot


async def latest_snapshot(db, user_id: str) -> dict | None:
    docs = await db["portfolio_snapshots"].find({"user_id": user_id}).sort("at", -1).limit(1).to_list(length=1)
    if not docs:
        return None
    docs[0].pop("_id", None)
    return docs[0]
