"""Stock health: the facts each holding's review rests on. Fundamentals and
the last four quarters of profit from yfinance, price trend from a year of
daily closes, and the last two weeks of headlines.

Fetched once per stock per IST day into `stock_health` (shared reference
data, no user_id: a stock's results are the same for everyone holding it),
so a 30-stock portfolio refreshed twice is not 60 research jobs.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import yfinance as yf

from backend.components.analyst.news import fresh_headlines
from backend.engine.session import IST

logger = logging.getLogger(__name__)

HEADLINE_MAX_AGE = timedelta(days=14)
HEADLINES = 5
_CONCURRENT = 5


def price_trend(closes: list[float]) -> dict:
    """50/200-day averages, the 52-week high and how far below it, and the
    three-month move, from daily closes oldest first."""
    if not closes:
        return {}
    last = closes[-1]

    def mean_of_last(n):
        return sum(closes[-n:]) / n if len(closes) >= n else None

    high = max(closes)
    return {
        "close": last,
        "sma_50": mean_of_last(50),
        "sma_200": mean_of_last(200),
        "high_52w": high,
        "below_high_pct": (high - last) / high * 100 if high else None,
        "return_3m_pct": (last - closes[-63]) / closes[-63] * 100 if len(closes) >= 63 else None,
    }


def _fundamentals_sync(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = t.info or {}
    profits = []
    try:
        statement = t.quarterly_income_stmt
        if statement is not None and "Net Income" in statement.index:
            # Columns are quarter ends, newest first.
            profits = [float(v) for v in statement.loc["Net Income"].dropna().tolist()[:4]]
    except Exception as exc:
        logger.info("no quarterly results for %s: %s", ticker, exc)
    return {
        "pe": info.get("trailingPE"),
        "roe": info.get("returnOnEquity"),
        # yfinance reports debt/equity as a percentage (e.g. 45.2 = 0.452x).
        "debt_to_equity": info.get("debtToEquity") / 100 if info.get("debtToEquity") is not None else None,
        "revenue_growth": info.get("revenueGrowth"),
        "quarterly_profit": profits,  # newest first
    }


async def _headlines(query: str) -> list[dict]:
    try:
        articles = await fresh_headlines([(query, "IN", "en-IN")], max_age=HEADLINE_MAX_AGE, limit=HEADLINES)
    except Exception as exc:
        logger.info("no headlines for %s: %s", query, exc)
        return []
    return [{"title": a.title, "url": a.url, "source": a.source, "published": a.published_at.isoformat()}
            for a in articles]


async def stock_health(db, stocks: list[dict], closes: dict[str, list[float]], now: datetime) -> dict[str, dict]:
    """`stocks` are scorecard rows ({symbol, name, exchange?}). Returns
    health per symbol; a fetch that fails leaves that part empty."""
    day = now.astimezone(IST).date().isoformat()
    cache = db["stock_health"]
    ids = [f"{s['symbol']}:{day}" for s in stocks]
    cached = {d["_id"]: d for d in await cache.find({"_id": {"$in": ids}}).to_list(length=None)}
    semaphore = asyncio.Semaphore(_CONCURRENT)

    async def one(stock) -> tuple[str, dict]:
        symbol = stock["symbol"]
        key = f"{symbol}:{day}"
        if key in cached:
            doc = cached[key]
        else:
            async with semaphore:
                ticker = f"{symbol}.BO" if stock.get("exchange") == "BSE" else f"{symbol}.NS"
                try:
                    fundamentals = await asyncio.to_thread(_fundamentals_sync, ticker)
                except Exception as exc:
                    logger.warning("portfolio: fundamentals failed for %s: %s", symbol, exc)
                    fundamentals = {}
                news = await _headlines(f"{stock.get('name') or symbol} share news")
            doc = {"_id": key, "fundamentals": fundamentals, "headlines": news,
                   "at": datetime.now(timezone.utc)}
            await cache.replace_one({"_id": key}, doc, upsert=True)
        return symbol, {
            "fundamentals": doc["fundamentals"], "headlines": doc["headlines"],
            "trend": price_trend(closes.get(symbol, [])),
        }

    return dict(await asyncio.gather(*(one(s) for s in stocks)))


def profit_trend(profits: list[float]) -> Optional[str]:
    """'falling' / 'rising' when each of the last three quarters is below /
    above the one before it (profits newest first); None otherwise."""
    if len(profits) < 4:
        return None
    steps = [profits[i] - profits[i + 1] for i in range(3)]
    if all(s < 0 for s in steps):
        return "falling"
    if all(s > 0 for s in steps):
        return "rising"
    return None
