from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Literal, Optional
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import time
from backend.configs.settings import settings

from backend.auth.dependency import get_optional_user, require_admin
from backend.auth.models import User
from backend.core.models import NewsArticle
from backend.datalayer.headlines import fetch_news_logic, fresh_headlines  # noqa: F401
import random

logger = logging.getLogger(__name__)

router = APIRouter()

# What an Indian trader checks before and during the session: the market
# itself, then the macro that moves it. Google News' `when:1d` keeps each
# search to the last day at the source. (This used to search Finnhub and
# Google for the ticker codes "^BSESN"/"^NSEI", which Finnhub has no news
# under and Google answered with stale single-stock quote pages.)
MARKET_QUERIES = [
    ("Sensex Nifty stock market when:1d", "IN", "en-IN"),
    ("Indian stock market today when:1d", "IN", "en-IN"),
    ("RBI rupee crude oil FII markets when:1d", "IN", "en-IN"),
]

FEED_FIELDS = {"title": 1, "url": 1, "source": 1, "published_at": 1, "scope": 1, "themes": 1, "event": 1,
               "impacts": 1, "symbols": 1, "material": 1, "status": 1}


@router.get("/news/feed")
async def news_feed(
    scope: Optional[Literal["COMPANY", "SECTOR", "MARKET", "MACRO", "GLOBAL"]] = None,
    mine: bool = False,
    material: bool = False,
    before: Optional[datetime] = None,
    q: Optional[str] = Query(None, max_length=80),
    limit: int = Query(50, ge=1, le=100),
    user: Optional[User] = Depends(get_optional_user),
):
    """The ingest worker's news store (backend/datalayer/news.py), newest
    first: relevant items, scored or still waiting to be. An NSE filing the
    scorer found moves nothing (record dates, "Updates") is left out. `mine`
    keeps the ones tagged with or moving a name the user holds (paper or at
    the broker) or watches; `before` pages back by published time; `q`
    matches the headline (case-insensitive, taken literally) or a symbol the
    item tags or moves. A search scans newest first until `limit` matches;
    a Mongo text index is the step up if that grows slow."""
    import re

    from backend.database import db
    from backend.datalayer.news import COLLECTION, SCORED, TRIAGED
    from backend.datalayer.prices import _bare
    from backend.portfolio.service import latest_snapshot

    query: dict = {"status": SCORED if material else {"$in": [SCORED, TRIAGED]},
                   "$nor": [{"source": "NSE filing", "status": SCORED, "impacts": {"$size": 0}}]}
    if material:
        query["material"] = True
    if scope:
        query["scope"] = scope
    if before:
        query["published_at"] = {"$lt": before}
    if mine and user:  # a guest has no holdings: `mine` is ignored
        held = await db.db["paper_positions"].distinct("symbol", {"user_id": user.id, "quantity": {"$ne": 0}})
        watched = await db.db["watchlist"].distinct("symbols", {"user_id": user.id})
        snapshot = await latest_snapshot(db.db, user.id)
        broker = [h.get("symbol") for h in (snapshot or {}).get("holdings", [])]
        names = sorted({_bare(s) for s in [*held, *watched, *broker] if s})
        query["$or"] = [{"symbols": {"$in": names}}, {"impacts.target": {"$in": names}}]
    if q and q.strip():
        term = q.strip()
        symbol = _bare(term).upper()
        query.setdefault("$and", []).append({"$or": [{"title": {"$regex": re.escape(term), "$options": "i"}},
                                                      {"symbols": symbol}, {"impacts.target": symbol}]})
    items = await db.db[COLLECTION].find(query, FEED_FIELDS).sort("published_at", -1).limit(limit).to_list(length=limit)
    return {"items": [as_feed_item(i) for i in items]}


def as_feed_item(item: dict) -> dict:
    """A news_items doc as the API shows it: `_id` -> `id`, aware UTC `published_at`."""
    item["id"] = item.pop("_id")
    if item["published_at"].tzinfo is None:  # Mongo hands back naive UTC
        item["published_at"] = item["published_at"].replace(tzinfo=timezone.utc)
    return item


OUTCOME_FIELDS = {"type": 1, "target": 1, "direction": 1, "impact": 1,
                  **{f"{p}_{h}": 1 for p in ("ret", "bench", "move") for h in ("1h", "1d", "5d")}}


@router.get("/news/item/{item_id}")
async def news_item(item_id: str, user: Optional[User] = Depends(get_optional_user)):
    """One news item with what the scorer predicted and what the market then did (news_outcomes rows; none
    while unscored). News is shared across users."""
    import re

    from backend.database import db
    from backend.datalayer.news import COLLECTION
    from backend.datalayer.outcomes import COLLECTION as OUTCOMES

    item = await db.db[COLLECTION].find_one({"_id": item_id}, FEED_FIELDS)
    if not item:
        raise HTTPException(status_code=404, detail="News item not found")
    rows = await db.db[OUTCOMES].find({"_id": {"$regex": f"^{re.escape(item_id)}:"}},
                                      OUTCOME_FIELDS).to_list(length=100)
    for r in rows:
        r.pop("_id")
    return {**as_feed_item(item), "outcomes": rows}


@router.get("/news/accuracy")
async def news_accuracy(refresh: bool = False, _admin: User = Depends(require_admin)):
    """The latest news accuracy report (datalayer/accuracy.py), built weekly
    by the ingest worker; `refresh` rebuilds it now. 404 before the first build."""
    from backend.database import db
    from backend.datalayer import accuracy

    doc = await accuracy.build(db.db) if refresh else await db.db[accuracy.COLLECTION].find_one({"_id": "latest"})
    if not doc:
        raise HTTPException(status_code=404, detail="No news accuracy report yet")
    doc.pop("_id", None)
    if doc["as_of"].tzinfo is None:  # Mongo hands back naive UTC
        doc["as_of"] = doc["as_of"].replace(tzinfo=timezone.utc)
    return {**doc, "company_scan_ok": accuracy.company_scan_ok(doc)}


@router.get("/news/filings")
async def news_filings(_admin: User = Depends(require_admin)):
    """The filing lane against its fixed bar (datalayer/filings.py). Recording only."""
    from backend.database import db
    from backend.datalayer import filings

    return await filings.report(db.db, db.redis)


SYMBOLS_LIMIT = 100
HEADLINE_HOURS = 72


@router.get("/news/symbols")
async def symbol_news(symbols: str = "", user: Optional[User] = Depends(get_optional_user)):
    """What the news layer says about each listed stock, for list pages:
    its blended sentiment and its latest scored headline (72h). Quiet names
    are left out."""
    from backend.database import db
    from backend.datalayer.news import COLLECTION, SCORED, ref
    from backend.datalayer.prices import _bare
    from backend.strategies.longterm.analyst_verdict import MATERIALITY_THRESHOLD

    wanted = list(dict.fromkeys(_bare(s.strip()).upper() for s in symbols.split(",") if s.strip()))[:SYMBOLS_LIMIT]
    if not wanted:
        return {"symbols": {}}
    since = datetime.now(timezone.utc) - timedelta(hours=HEADLINE_HOURS)
    latest: dict[str, dict] = {}
    docs = await db.db[COLLECTION].find(
        {"status": SCORED, "published_at": {"$gte": since}, "impacts.target": {"$in": wanted}},
        {"title": 1, "url": 1, "published_at": 1, "impacts": 1, "material": 1},
    ).sort("published_at", -1).to_list(length=1000)
    # Newest first: the latest material item on a symbol wins (bad news must
    # not hide behind a later minor one), else its latest item. Material is
    # judged on this symbol's own impact, not the item's strongest target.
    for doc in docs:
        for impact in doc.get("impacts") or []:
            target = impact.get("target")
            if impact.get("type") != "symbol" or target not in wanted:
                continue
            material = (impact.get("impact") or 0) >= MATERIALITY_THRESHOLD
            if target in latest and (latest[target]["material"] or not material):
                continue
            published = doc["published_at"]
            latest[target] = {
                "headline": doc.get("title"), "url": doc.get("url"), "direction": impact.get("direction"),
                "impact": impact.get("impact"), "material": material,
                "published_at": (published if published.tzinfo else published.replace(tzinfo=timezone.utc)),
                **ref(doc),
            }
    empty = {"headline": None, "direction": None, "impact": None, "material": False, "published_at": None,
             "url": None, "id": None, "impacts": []}
    sentiments: dict[str, float] = {}
    if db.redis is not None:
        try:  # one round trip for every symbol, not one each
            raws = await db.redis.mget([f"sentiment:{s}" for s in wanted])
            sentiments = {s: float(v) for s, v in zip(wanted, raws) if v is not None}
        except Exception as exc:
            logger.warning("sentiment cache unavailable for the news summary: %s", exc)
    out = {}
    for symbol in wanted:
        sentiment = sentiments.get(symbol)
        if sentiment is None and symbol not in latest:
            continue
        out[symbol] = {"sentiment": sentiment, **empty, **latest.get(symbol, {})}
    return {"symbols": out}


HISTORY_LIMIT = 500
LIVE_NEWS_TTL = 900


async def _live_headlines(symbol: str, since: datetime) -> list[dict]:
    """Google News for a stock with nothing stored, no model call and so no direction or impact. Only
    real NSE names reach Google, each at most once per TTL, because guests can ask for any symbol."""
    from backend.database import db
    from backend.instruments.master import InstrumentMaster
    from backend.market_cache import cached

    if not await InstrumentMaster(db.db).known("NSE", symbol):
        return []

    async def fetch() -> list[dict]:
        return [{"id": None, "title": a.title, "url": a.url, "source": a.source,
                 "published_at": a.published_at.replace(tzinfo=timezone.utc).isoformat(),
                 "direction": None, "impact": None, "material": False, "impacts": []}
                for a in await fetch_news_logic([symbol])]

    rows = await cached(f"symbol_news:{symbol}", LIVE_NEWS_TTL, fetch) or []
    return [r for r in rows if datetime.fromisoformat(r["published_at"]) >= since]


@router.get("/news/symbol/{symbol}")
async def symbol_history(symbol: str, days: int = Query(180, ge=1, le=365), live: bool = False,
                         user: Optional[User] = Depends(get_optional_user)):
    """Scored news on one stock over `days`, newest first (at most 500), for
    the chart's news markers: each item with THIS symbol's direction and
    impact, material judged on that impact (an item only tagged with the
    symbol has direction/impact None and is not material). `live`: when none are
    stored, the latest unscored headlines instead (the chart's markers leave it off)."""
    from backend.database import db
    from backend.datalayer.news import COLLECTION, SCORED, ref
    from backend.datalayer.prices import _bare
    from backend.strategies.longterm.analyst_verdict import MATERIALITY_THRESHOLD

    sym = _bare(symbol.strip()).upper()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # Both $or branches ride an index: (impacts.target,published_at) and (symbols,published_at).
    docs = await db.db[COLLECTION].find(
        {"status": SCORED, "published_at": {"$gte": since}, "$or": [{"impacts.target": sym}, {"symbols": sym}]},
        {"title": 1, "url": 1, "published_at": 1, "impacts": 1},
    ).sort("published_at", -1).to_list(length=HISTORY_LIMIT)
    items = []
    for doc in docs:
        own = next((i for i in doc.get("impacts") or [] if i.get("type") == "symbol" and i.get("target") == sym), {})
        published = doc["published_at"]
        items.append({"id": doc["_id"], "title": doc.get("title"), "url": doc.get("url"),
                      "published_at": published if published.tzinfo else published.replace(tzinfo=timezone.utc),
                      "direction": own.get("direction"), "impact": own.get("impact"),
                      "material": (own.get("impact") or 0) >= MATERIALITY_THRESHOLD, "impacts": ref(doc)["impacts"]})
    return {"symbol": sym, "items": items or (await _live_headlines(sym, since) if live else [])}


RESULTS_DAYS = 120


@router.get("/news/results")
async def symbol_results(symbols: str = "", user: Optional[User] = Depends(get_optional_user)):
    """Each listed stock's next results date within RESULTS_DAYS, read from the
    stored corporate-events calendar (mine/events.py fills it for held symbols
    only; nothing is fetched here). Names without a known date are left out."""
    from backend.database import db
    from backend.datalayer.bars import today_ist
    from backend.datalayer.prices import _bare
    from backend.mine import events

    wanted = list(dict.fromkeys(_bare(s.strip()).upper() for s in symbols.split(",") if s.strip()))[:SYMBOLS_LIMIT]
    if not wanted:
        return {"results": {}}
    out: dict[str, str] = {}
    for e in await events.upcoming(db.db, wanted, today_ist(), RESULTS_DAYS):
        if e["kind"] == "results":
            out.setdefault(e["symbol"], e["date"])  # sorted by date: the first is the next
    return {"results": out}
