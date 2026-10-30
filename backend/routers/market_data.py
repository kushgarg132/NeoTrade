from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
import json
import yfinance as yf
import logging
import asyncio
import time

from backend.auth.dependency import get_current_user
from backend.auth.models import User
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
    "TCS.NS", "TATACONSUM.NS", "TMPV.NS", "TATASTEEL.NS", "TECHM.NS",
    "TITAN.NS", "ULTRACEMCO.NS", "UPL.NS", "WIPRO.NS"
]

# How long a feed is fresh; older ones are still served while a refresh
# runs (backend/market_cache.py).
QUOTES_TTL = 60
MOVERS_TTL = 5 * 60


def _movers_sync() -> List[Dict[str, Any]]:
    """The NIFTY 50's top five gainers then top five losers today, from one batched
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
    now = time.time()
    for m in movers:
        m["at"] = now
    movers.sort(key=lambda m: m["percent"], reverse=True)
    gainers = [m for m in movers if m["percent"] > 0][:5]
    losers = [m for m in reversed(movers) if m["percent"] < 0][:5]
    return gainers + losers


async def _quotes(names_to_symbols: Dict[str, str]) -> List[Dict[str, Any]]:
    # The ingest worker keeps these in Redis (backend/datalayer/prices.py);
    # fetch here only when it is down or has not caught up.
    from backend.database import db
    from backend.datalayer.prices import macro_rows

    rows = {r["name"]: r for r in await macro_rows(db.redis, names_to_symbols)}
    missing = [name for name in names_to_symbols if name not in rows]
    if missing:
        now = time.time()
        fetched = await asyncio.gather(*(fetch_ticker_data(names_to_symbols[name], name) for name in missing))
        rows.update({r["name"]: {**r, "at": now} for r in fetched if r})
    return [rows[name] for name in names_to_symbols if name in rows]


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


def _fetch_index_intraday_sync(ticker: str) -> List[Dict[str, Any]]:
    hist = yf.Ticker(ticker).history(period="1d", interval="5m")
    if hist is None or hist.empty:
        return []
    return [{"t": index.isoformat(), "close": float(row["Close"])} for index, row in hist.iterrows()]


_INTRADAY_TTL = 60
_INTRADAY_EMPTY_TTL = 15  # negative cache: a yfinance outage must not be re-hit on every mount
_intraday_cache: Dict[str, tuple] = {}


@router.get("/market/index/{ticker}/intraday")
async def get_index_intraday(ticker: str):
    """Today's 5-minute closes for a tracked index, cached 60 s per ticker in-process."""
    if ticker not in _known_index_names():
        raise HTTPException(status_code=404, detail=f"{ticker} is not a tracked index")
    hit = _intraday_cache.get(ticker)
    if hit and time.monotonic() - hit[0] < (_INTRADAY_TTL if hit[1] else _INTRADAY_EMPTY_TTL):
        if not hit[1]:
            raise HTTPException(status_code=502, detail="No intraday data right now")
        return hit[1]
    try:
        points = await asyncio.to_thread(_fetch_index_intraday_sync, ticker)
    except Exception as e:
        logger.error(f"Error fetching intraday for {ticker}: {e}")
        points = []
    _intraday_cache[ticker] = (time.monotonic(), points)
    if not points:
        raise HTTPException(status_code=502, detail="No intraday data right now")
    return points


@router.get("/market/brief")
async def get_market_brief():
    """The AI market brief the ingest worker last wrote (Redis `market:brief`). Never calls the model."""
    from backend.database import db
    from backend.datalayer.market import latest_brief

    brief = await latest_brief(db.redis)
    if brief is None:
        raise HTTPException(status_code=404, detail="No market brief yet")
    return brief


@router.get("/research/{symbol}/note")
async def get_cached_note(symbol: str):
    """The last analyst read for this stock, as {summary, thesis, as_of, read, at, stale}. Never calls the
    model: 404 when nothing is cached."""
    from backend.ai.analyst import latest

    last = await latest(symbol.strip().upper())
    read = (last or {}).get("read") or {}
    summary = (read.get("summary") or "").strip()
    if not summary or summary == "Unable to generate summary.":
        raise HTTPException(status_code=404, detail="No cached note")
    return {"summary": summary, "thesis": read.get("thesis") or "", "as_of": last["at"],
            "read": read, "at": last["at"], "stale": last["stale"]}


@router.get("/market/index/{ticker}/analysis")
async def get_index_analysis(ticker: str, cached: bool = False):
    """AI-written explanation of why this index moved in its latest session,
    with the session figures and headlines it was written from. Explains the
    past only -- no forecasts, no calls. `cached=true` returns only a stored
    one, never calling the model: 404 when there is none."""
    from backend.research.index_move import ExplanationUnavailable, cached_index_move, explain_index_move

    name = _known_index_names().get(ticker)
    if name is None:
        raise HTTPException(status_code=404, detail=f"{ticker} is not a tracked index")
    if cached:
        if (story := await cached_index_move(ticker)) is None:
            raise HTTPException(status_code=404, detail="No stored explanation")
        return story
    try:
        return await explain_index_move(ticker, name)
    except ExplanationUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


_MAX_QUOTES = 8
# Suggestion prices expire hard, unlike the stale-while-revalidate feeds:
# typeahead sets rarely repeat within a minute, so a served-at-any-age entry
# would show days-old prices. Per worker, in memory, bounded.
_quote_cache: Dict[str, tuple] = {}
_QUOTE_CACHE_MAX = 500


def _quotes_sync(symbols: List[str]) -> List[Dict[str, Any]]:
    """Last price and day change for a few NSE symbols, one batched download."""
    import pandas as pd

    raw = yf.download([f"{s}.NS" for s in symbols], period="5d", interval="1d", group_by="ticker",
                      progress=False, threads=True)
    quotes = []
    for symbol in symbols:
        if isinstance(raw.columns, pd.MultiIndex):
            if f"{symbol}.NS" not in raw.columns.get_level_values(0):
                continue
            frame = raw[f"{symbol}.NS"]
        elif len(symbols) == 1 and "Close" in raw.columns:
            frame = raw
        else:
            continue
        closes = frame["Close"].dropna()
        if len(closes) < 2:
            continue
        price, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
        quotes.append({"symbol": symbol, "price": round(price, 2),
                       "change_pct": round((price - prev) / prev * 100, 2) if prev else 0.0, "at": time.time()})
    return quotes


async def _cached_quotes(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """The ingest worker's `quote:` rows (Nifty 200 plus held and watched names,
    refreshed every 15 s to 10 min, backend/datalayer/prices.py::quotes)."""
    import json

    from backend.database import db
    from backend.marks import QUOTE_KEY

    if db.redis is None:
        return {}
    try:
        raws = await db.redis.mget([QUOTE_KEY.format(s) for s in symbols])
    except Exception as exc:
        logger.warning("quote cache read failed: %s", exc)
        return {}
    found = {}
    for symbol, raw in zip(symbols, raws):
        q = json.loads(raw) if raw else {}
        if q.get("ltp"):
            prev = q.get("prev_close")
            found[symbol] = {"symbol": symbol, "price": round(float(q["ltp"]), 2), "prev_close": prev,
                             "change_pct": round((q["ltp"] - prev) / prev * 100, 2) if prev else None, "at": q["at"]}
    return found


SCAN_TTL = 5 * 60
SCAN_TOP = 10
NEAR_52W = 0.02  # within 2% of the 52-week high or low counts as "near"


def market_scan(rows: List[Dict[str, str]], quotes: Dict[str, Dict[str, Any]], ranges: Dict[str, tuple]) -> Dict[str, Any]:
    """The Nifty 200 at a glance from cached quotes and a year of daily bars: top gainers and losers, names
    near their 52-week high or low, and each sector's average day change. `rows` from
    news_sources.universe_rows, `quotes` from _cached_quotes, `ranges` symbol -> (52w high, 52w low). Pure."""
    movers = []
    for r in rows:
        q = quotes.get(r["symbol"])
        if q and q.get("change_pct") is not None:
            hi, lo = ranges.get(r["symbol"], (None, None))
            movers.append({"symbol": r["symbol"], "name": r["name"], "sector": r["sector"], "price": q["price"],
                           "change_pct": q["change_pct"], "high_52w": hi, "low_52w": lo})
    by_change = sorted(movers, key=lambda m: m["change_pct"], reverse=True)
    near_high = sorted((m for m in movers if m["high_52w"] and m["price"] >= m["high_52w"] * (1 - NEAR_52W)),
                       key=lambda m: m["price"] / m["high_52w"], reverse=True)
    near_low = sorted((m for m in movers if m["low_52w"] and m["price"] <= m["low_52w"] * (1 + NEAR_52W)),
                      key=lambda m: m["price"] / m["low_52w"])
    groups: Dict[str, list] = {}
    for m in movers:
        groups.setdefault(m["sector"], []).append(m["change_pct"])
    sectors = sorted(({"sector": k, "change_pct": round(sum(v) / len(v), 2), "up": sum(x > 0 for x in v), "n": len(v)}
                      for k, v in groups.items()), key=lambda x: x["change_pct"], reverse=True)
    return {
        "movers": by_change,
        "gainers": [m for m in by_change if m["change_pct"] > 0][:SCAN_TOP],
        "losers": [m for m in reversed(by_change) if m["change_pct"] < 0][:SCAN_TOP],
        "near_high": near_high[:SCAN_TOP], "near_low": near_low[:SCAN_TOP], "sectors": sectors,
        "breadth": {"up": sum(m["change_pct"] > 0 for m in movers), "down": sum(m["change_pct"] < 0 for m in movers),
                    "n": len(movers)},
        "at": max((quotes[m["symbol"]]["at"] for m in movers), default=None),
    }


async def _scan() -> Dict[str, Any]:
    from datetime import timedelta

    from backend.database import db
    from backend.datalayer import news_sources
    from backend.datalayer.bars import BARS, today_ist

    rows = news_sources.universe_rows()
    symbols = [r["symbol"] for r in rows]
    quotes = await _cached_quotes(symbols)
    if not quotes or db.db is None:
        return {}  # the ingest worker has not run: not cached, asked again next time
    since = (today_ist() - timedelta(days=365)).isoformat()
    ranges = {r["_id"]: (r["hi"], r["lo"]) async for r in db.db[BARS].aggregate([
        {"$match": {"symbol": {"$in": symbols}, "date": {"$gte": since}}},
        {"$group": {"_id": "$symbol", "hi": {"$max": "$high"}, "lo": {"$min": "$low"}}}])}
    return market_scan(rows, quotes, ranges)


@router.get("/market/scan")
async def get_market_scan():
    """Nifty 200 gainers, losers, 52-week highs and lows, sector moves (cached 5 min), each sector with its
    news sentiment read fresh (one MGET; not cached with the scan)."""
    scan = await cached("scan", SCAN_TTL, _scan) or {}
    scan = {k: v for k, v in scan.items() if k != "movers"}  # the cache entry keeps it (sector page)
    from backend.database import db

    symbols = [m["symbol"] for m in scan.get("gainers", []) + scan.get("losers", [])]
    with_news = set()
    if symbols:
        try:
            from datetime import datetime, timedelta, timezone
            from backend.datalayer.news import COLLECTION, SCORED

            docs = await db.db[COLLECTION].find(
                {"status": SCORED, "published_at": {"$gte": datetime.now(timezone.utc) - timedelta(hours=24)},
                 "impacts": {"$elemMatch": {"type": "symbol", "target": {"$in": symbols}}}},
                {"impacts": 1}).to_list(length=None)
            with_news = {i["target"] for d in docs for i in d.get("impacts", []) if i.get("type") == "symbol"}
        except Exception as exc:
            logger.warning("news flags unavailable for the scan: %s", exc)
            with_news = set()
    for k in ("gainers", "losers"):
        if k in scan:
            scan[k] = [{**m, "news": m["symbol"] in with_news} for m in scan[k]]
    if not scan.get("sectors"):
        return scan
    raws = []
    if db.redis is not None:
        try:
            raws = await db.redis.mget([f"sector_sentiment:{s['sector']}" for s in scan["sectors"]])
        except Exception as exc:
            logger.warning("sector sentiment unavailable for the scan: %s", exc)
    return {**scan, "sectors": with_sentiment(scan["sectors"], raws)}


def sector_members(scan: Dict[str, Any], name: str) -> List[Dict[str, Any]]:
    """The scan's movers in one sector, best day first. Pure."""
    return [m for m in scan.get("movers", []) if m["sector"] == name]


@router.get("/market/sector/{name}")
async def get_sector(name: str, user: User = Depends(get_current_user)):
    """One sector: its day move and sentiment, its Nifty 200 members, and the 20 newest news items that move
    it. 404 for a sector not in the scan."""
    from backend.database import db
    from backend.datalayer.news import COLLECTION
    from backend.routers.news import FEED_FIELDS, as_feed_item

    scan = await cached("scan", SCAN_TTL, _scan) or {}
    row = next((s for s in scan.get("sectors", []) if s["sector"] == name), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown sector")
    raws = []
    if db.redis is not None:
        try:
            raws = await db.redis.mget([f"sector_sentiment:{name}"])
        except Exception as exc:
            logger.warning("sector sentiment unavailable for %s: %s", name, exc)
    (row,) = with_sentiment([row], raws)
    items = await db.db[COLLECTION].find(
        {"impacts": {"$elemMatch": {"type": "sector", "target": name}}}, FEED_FIELDS
    ).sort("published_at", -1).limit(20).to_list(length=20)
    return {"sector": name, "change_pct": row["change_pct"], "up": row["up"], "n": row["n"],
            "sentiment": row["sentiment"], "members": sector_members(scan, name),
            "news": [as_feed_item(i) for i in items], "at": scan.get("at")}


def with_sentiment(sectors: List[Dict[str, Any]], raws: list) -> List[Dict[str, Any]]:
    """Each sector row plus `sentiment` (-1..1) from its `sector_sentiment:{sector}` JSON; absent, unreadable
    or a None score is None, never 0. `raws` in `sectors` order (may be shorter, e.g. Redis down). Pure."""
    def score(raw):
        try:
            value = json.loads(raw)["score"]
            return None if value is None else round(float(value), 2)
        except (TypeError, ValueError, KeyError):
            return None
    return [{**s, "sentiment": score(raws[i] if i < len(raws) else None)} for i, s in enumerate(sectors)]


@router.get("/market/quotes")
async def get_quotes(symbols: str):
    """Last price, day change and `at` for up to 8 symbols (search suggestions,
    the Stock page, the watchlist): the ingest quote cache first, Yahoo only
    for the rest, cached per set."""
    wanted = list(dict.fromkeys(s.strip().upper().removesuffix(".NS") for s in symbols.split(",") if s.strip()))
    if not wanted or len(wanted) > _MAX_QUOTES:
        raise HTTPException(status_code=422, detail=f"Ask for 1 to {_MAX_QUOTES} symbols.")
    by_symbol = await _cached_quotes(wanted)
    missing = sorted(s for s in wanted if s not in by_symbol)
    if missing:
        key = ",".join(missing)
        hit = _quote_cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < QUOTES_TTL:
            quotes = hit[1]
        else:
            quotes = await asyncio.to_thread(_quotes_sync, missing)
            if len(_quote_cache) >= _QUOTE_CACHE_MAX:
                _quote_cache.clear()  # ponytail: wholesale reset, an LRU if hit rates ever matter
            _quote_cache[key] = (time.monotonic(), quotes)
        by_symbol.update({q["symbol"]: q for q in quotes})
    return [by_symbol[s] for s in wanted if s in by_symbol]
