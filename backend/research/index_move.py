"""Why did an index move today? An AI-written explanation of one index's
latest session, grounded in facts gathered here first: the session's own
OHLC, its recent trend, what the other tracked indices did, the day's
biggest NIFTY 50 movers (for Indian indices), and recent headlines.

The model only explains; the prompt (backend/prompts/index_move.md) forbids
forecasts and buy/sell calls. Explanations are cached per index for a few
minutes -- a tap should not cost an LLM call every time, and the headlines
behind it do not change that fast.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf

from backend.components.analyst.news import fresh_headlines
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)

CACHE_SECONDS = 15 * 60
_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}

INDIAN = {"^NSEI", "^BSESN", "^NSEBANK", "^INDIAVIX"}

# What to search for, per index: an Indian index's move is usually explained
# by domestic market wrap-ups, a global one by its own market's.
NEWS_QUERIES: Dict[str, List[tuple[str, str, str]]] = {
    "^NSEI": [("Nifty 50 today", "IN", "en-IN"), ("stock market India today Sensex Nifty", "IN", "en-IN")],
    "^BSESN": [("Sensex today", "IN", "en-IN"), ("stock market India today Sensex Nifty", "IN", "en-IN")],
    "^NSEBANK": [("Bank Nifty today", "IN", "en-IN"), ("bank stocks India today", "IN", "en-IN")],
    "^INDIAVIX": [("India VIX today", "IN", "en-IN"), ("stock market India volatility today", "IN", "en-IN")],
    "^GSPC": [("S&P 500 stocks today", "US", "en-US")],
    "^IXIC": [("Nasdaq composite today", "US", "en-US")],
    "^FTSE": [("FTSE 100 today", "GB", "en-GB")],
    "^N225": [("Nikkei 225 today", "US", "en-US")],
    "^GDAXI": [("DAX index today", "US", "en-US")],
}

HEADLINE_LIMIT = 12
HEADLINE_MAX_AGE = timedelta(hours=48)


class ExplanationUnavailable(Exception):
    """The model could not be reached or returned nothing usable."""


def _session_sync(ticker: str) -> Optional[Dict[str, Any]]:
    hist = yf.Ticker(ticker).history(period="1mo", interval="1d")
    if hist is None or len(hist) < 2:
        return None
    closes = [float(c) for c in hist["Close"]]
    last, prev = hist.iloc[-1], hist.iloc[-2]
    close, prev_close = float(last["Close"]), float(prev["Close"])

    def pct(new: float, old: float) -> float:
        return (new - old) / old * 100 if old else 0.0

    return {
        "date": hist.index[-1].strftime("%Y-%m-%d"),
        "open": float(last["Open"]),
        "high": float(last["High"]),
        "low": float(last["Low"]),
        "close": close,
        "previous_close": prev_close,
        "change": close - prev_close,
        "percent": pct(close, prev_close),
        "gap_percent": pct(float(last["Open"]), prev_close),
        "five_session_percent": pct(close, closes[-6]) if len(closes) >= 6 else None,
        "month_percent": pct(close, closes[0]),
    }


def _format_session(s: Dict[str, Any]) -> str:
    return "\n".join([
        f"- Close {s['close']:,.2f}, previous close {s['previous_close']:,.2f}: "
        f"{s['change']:+,.2f} ({s['percent']:+.2f}%)",
        f"- Opened at {s['open']:,.2f} ({s['gap_percent']:+.2f}% against the previous close)",
        f"- Day's range {s['low']:,.2f} to {s['high']:,.2f}",
    ])


def _format_trend(s: Dict[str, Any]) -> str:
    lines = []
    if s["five_session_percent"] is not None:
        lines.append(f"- Over the last five sessions: {s['five_session_percent']:+.2f}%")
    lines.append(f"- Over the last month: {s['month_percent']:+.2f}%")
    return "\n".join(lines)


async def _headlines(ticker: str) -> List[Dict[str, Any]]:
    """The highest-impact scored market, macro and global items the ingest
    worker stored (backend/datalayer/news.py); a fresh Google search only
    when it has none."""
    from backend.database import db
    from backend.datalayer.market import top_items

    scopes = ("MARKET", "MACRO", "GLOBAL") if ticker in INDIAN else ("GLOBAL",)
    try:
        stored = await top_items(db.db, hours=HEADLINE_MAX_AGE.total_seconds() / 3600, scopes=scopes,
                                 limit=HEADLINE_LIMIT) if db.db is not None else []
    except Exception as e:
        logger.warning("index_move: stored headlines unavailable: %s", e)
        stored = []
    if stored:
        return [{"title": d["title"], "url": d.get("url", ""), "source": d.get("source", ""),
                 "published_at": d["published_at"].isoformat()} for d in stored]
    articles = await fresh_headlines(NEWS_QUERIES.get(ticker, []), max_age=HEADLINE_MAX_AGE, limit=HEADLINE_LIMIT)
    return [
        {"title": a.title, "url": a.url, "source": a.source, "published_at": a.published_at.isoformat()}
        for a in articles
    ]


async def _peers(ticker: str) -> List[Dict[str, Any]]:
    # Imported here: backend.routers.market_data imports this module.
    from backend.routers.market_data import GLOBAL_INDICES, INDICES, fetch_ticker_data

    others = {name: sym for name, sym in {**INDICES, **GLOBAL_INDICES}.items() if sym != ticker}
    from backend.database import db
    from backend.datalayer.prices import macro_rows

    cached = await macro_rows(db.redis, others)
    if cached is not None:
        return cached
    results = await asyncio.gather(*(fetch_ticker_data(sym, name) for name, sym in others.items()))
    return [r for r in results if r]


async def _movers(ticker: str) -> List[Dict[str, Any]]:
    if ticker not in INDIAN:
        return []
    from backend.routers.market_data import get_trending_stocks

    try:
        return await get_trending_stocks()
    except Exception as e:
        logger.warning("index_move: movers unavailable: %s", e)
        return []


def _bullets(rows: List[str], empty: str) -> str:
    return "\n".join(rows) if rows else empty


async def explain_index_move(ticker: str, name: str) -> Dict[str, Any]:
    cached = _cache.get(ticker)
    if cached and cached[0] > time.time():
        return {**cached[1], "cached": True}

    session, headlines, peers, movers = await asyncio.gather(
        asyncio.to_thread(_session_sync, ticker), _headlines(ticker), _peers(ticker), _movers(ticker),
    )
    if session is None:
        raise ExplanationUnavailable(f"No recent sessions for {name}")

    system, prompt = render(
        "index_move",
        name=name,
        session_date=session["date"],
        session=_format_session(session),
        trend=_format_trend(session),
        peers=_bullets([f"- {p['name']}: {p['percent']:+.2f}%" for p in peers], "No data for other indices."),
        movers=_bullets(
            [f"- {m['symbol'].removesuffix('.NS')}: {m['percent']:+.2f}%" for m in movers],
            "No mover data.",
        ),
        headlines=_bullets(
            [f"- {h['title']} ({h['source']}, {h['published_at'][:16].replace('T', ' ')})" for h in headlines],
            "No recent headlines were found.",
        ),
    )
    text = (await llm_service.get_completion(prompt, system_prompt=system, tier="standard") or "").strip()
    # get_completion reports failure as text rather than raising.
    if not text or text == "LLM_DISABLED" or text.startswith("Error generating response"):
        raise ExplanationUnavailable("The analysis model is unavailable right now")

    result = {
        "ticker": ticker,
        "name": name,
        "session": session,
        "analysis": text,
        "headlines": headlines,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    _cache[ticker] = (time.time() + CACHE_SECONDS, result)
    return result
