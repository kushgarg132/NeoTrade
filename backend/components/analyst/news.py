from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Literal, Optional
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import time
from backend.configs.settings import settings

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.market_cache import cached
from backend.components.shared.models import NewsArticle
import random

logger = logging.getLogger(__name__)

router = APIRouter()

class NewsFetchResponse(BaseModel):
    articles: List[NewsArticle]

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
HEADLINE_MAX_AGE = timedelta(hours=36)
MARKET_NEWS_TTL_SECONDS = 10 * 60


def _title_key(title: str) -> str:
    """Google News titles end in " - Source"; the same story from two
    outlets, or twice from one, should count once."""
    return title.rsplit(" - ", 1)[0].strip().lower()


async def fresh_headlines(
    queries, max_age: timedelta = HEADLINE_MAX_AGE, limit: int = 10
) -> List[NewsArticle]:
    """Newest-first headlines across Google News searches, none older than
    `max_age`, each story once. `queries` is (query, region, lang) tuples."""
    batches = await asyncio.gather(
        *(fetch_google_news(q, region=r, lang=l, limit=limit * 2) for q, r, l in queries),
        return_exceptions=True,
    )
    # fetch_google_news returns naive UTC timestamps.
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - max_age
    seen, fresh = set(), []
    for batch in batches:
        if isinstance(batch, BaseException):
            continue
        for article in batch:
            key = _title_key(article.title)
            if key in seen or article.published_at < cutoff:
                continue
            seen.add(key)
            fresh.append(article)
    fresh.sort(key=lambda a: a.published_at, reverse=True)
    return fresh[:limit]


@router.get("/news/market", response_model=NewsFetchResponse)
async def fetch_market_news():
    """Today's Indian market headlines, newest first. Refreshed every ten
    minutes behind a stale-while-revalidate cache (backend/market_cache.py):
    every statement view asks, and none should wait on Google News."""
    async def fetch():
        return [a.model_dump(mode="json") for a in await fresh_headlines(MARKET_QUERIES)]

    return NewsFetchResponse(articles=await cached("news", MARKET_NEWS_TTL_SECONDS, fetch))

async def fetch_news_logic(symbols: List[str], limit: int = 10) -> List[NewsArticle]:
    """Recent news per symbol from Google News India. Used on demand for
    symbols the ingest worker does not follow (backend/datalayer/news.py
    covers the Nifty 200 and every held or watched name)."""
    logger.info(f"Fetching news for symbols: {symbols}, limit: {limit}")
    articles = []
    for symbol in symbols:
        bare = symbol.removesuffix(".NS").removesuffix(".BO")
        current = await fetch_google_news(f"{bare} share price news", region="IN", lang="en-IN", limit=limit)
        seen, unique = set(), []
        for a in current:
            if a.url not in seen:
                seen.add(a.url)
                unique.append(a)
        unique.sort(key=lambda x: x.published_at, reverse=True)
        articles.extend(unique[:limit])
    return articles

import requests
from bs4 import BeautifulSoup

async def fetch_google_news(query: str, region: str = "US", lang: str = "en-US", limit: int = 10) -> List[NewsArticle]:
    """
    Fetches news from Google News RSS Feed.
    """
    base_url = "https://news.google.com/rss/search"
    params = {
        "q": query,
        "hl": lang,
        "gl": region,
        "ceid": f"{region}:{lang.split('-')[0]}"
    }
    
    try:
        logger.info(f"Querying Google News RSS: {query} ({region})")
        response = await asyncio.to_thread(requests.get, base_url, params=params, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, features="xml")
        items = soup.find_all("item")
        
        articles = []
        for item in items[:limit]:
            title = item.title.text if item.title else "No Title"
            link = item.link.text if item.link else ""
            pub_date_str = item.pubDate.text if item.pubDate else ""
            source = item.source.text if item.source else "Google News"
            
            # Parse Date: "Fri, 12 Dec 2025 10:00:00 GMT"
            try:
                # Python 3.11+ can handle %z, but often RSS has GMT/EST which dateutil loves but strptime hates.
                # Simplified approach or use dateutil if available. 
                # Trying standard format first.
                from email.utils import parsedate_to_datetime
                pub_time = parsedate_to_datetime(pub_date_str)
                # Ensure offset awareness is handled or strip it for internal consistency if needed
                if pub_time.tzinfo:
                     pub_time = pub_time.replace(tzinfo=None) # naive for now to match YF often
            except Exception:
                pub_time = datetime.now()
                
            articles.append(NewsArticle(
                title=title,
                url=link,
                source=source,
                published_at=pub_time,
                related_symbols=[query.split()[0]]
            ))
            
        return articles
        
    except Exception as e:
        logger.error(f"Google News Fetch Failed: {e}")
        return []


FEED_FIELDS = {"title": 1, "url": 1, "source": 1, "published_at": 1, "scope": 1, "themes": 1, "event": 1,
               "impacts": 1, "symbols": 1, "material": 1, "status": 1}


@router.get("/news/feed")
async def news_feed(
    scope: Optional[Literal["COMPANY", "SECTOR", "MARKET", "MACRO", "GLOBAL"]] = None,
    mine: bool = False,
    material: bool = False,
    before: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    """The ingest worker's news store (backend/datalayer/news.py), newest
    first: relevant items, scored or still waiting to be. `mine` keeps the
    ones tagged with or moving a name the user holds or watches; `before`
    pages back by published time."""
    from backend.database import db
    from backend.datalayer.news import COLLECTION, SCORED, TRIAGED
    from backend.datalayer.prices import _bare

    query: dict = {"status": SCORED if material else {"$in": [SCORED, TRIAGED]}}
    if material:
        query["material"] = True
    if scope:
        query["scope"] = scope
    if before:
        query["published_at"] = {"$lt": before}
    if mine:
        held = await db.db["paper_positions"].distinct("symbol", {"user_id": user.id, "quantity": {"$ne": 0}})
        watched = await db.db["watchlist"].distinct("symbols", {"user_id": user.id})
        names = sorted({_bare(s) for s in [*held, *watched] if s})
        query["$or"] = [{"symbols": {"$in": names}}, {"impacts.target": {"$in": names}}]
    items = await db.db[COLLECTION].find(query, FEED_FIELDS).sort("published_at", -1).limit(limit).to_list(length=limit)
    for item in items:
        item["id"] = item.pop("_id")
        if item["published_at"].tzinfo is None:  # Mongo hands back naive UTC
            item["published_at"] = item["published_at"].replace(tzinfo=timezone.utc)
    return {"items": items}


SYMBOLS_LIMIT = 100
HEADLINE_HOURS = 72


@router.get("/news/symbols")
async def symbol_news(symbols: str = "", user: User = Depends(get_current_user)):
    """What the news layer says about each listed stock, for list pages:
    its blended sentiment and its latest scored headline (72h). Quiet names
    are left out."""
    from backend.ai.sentiment import get_cached_sentiment
    from backend.database import db
    from backend.datalayer.news import COLLECTION, SCORED
    from backend.datalayer.prices import _bare

    wanted = list(dict.fromkeys(_bare(s.strip()).upper() for s in symbols.split(",") if s.strip()))[:SYMBOLS_LIMIT]
    if not wanted:
        return {"symbols": {}}
    since = datetime.now(timezone.utc) - timedelta(hours=HEADLINE_HOURS)
    latest: dict[str, dict] = {}
    docs = await db.db[COLLECTION].find(
        {"status": SCORED, "published_at": {"$gte": since}, "impacts.target": {"$in": wanted}},
        {"title": 1, "url": 1, "published_at": 1, "impacts": 1, "material": 1},
    ).sort("published_at", -1).to_list(length=1000)
    for doc in docs:
        for impact in doc.get("impacts") or []:
            target = impact.get("target")
            if impact.get("type") == "symbol" and target in wanted and target not in latest:
                published = doc["published_at"]
                latest[target] = {
                    "headline": doc.get("title"), "url": doc.get("url"), "direction": impact.get("direction"),
                    "impact": impact.get("impact"), "material": bool(doc.get("material")),
                    "published_at": (published if published.tzinfo else published.replace(tzinfo=timezone.utc)),
                }
    empty = {"headline": None, "direction": None, "impact": None, "material": False, "published_at": None,
             "url": None}
    out = {}
    for symbol in wanted:
        sentiment = await get_cached_sentiment(symbol, db.redis) if db.redis is not None else None
        if sentiment is None and symbol not in latest:
            continue
        out[symbol] = {"sentiment": sentiment, **empty, **latest.get(symbol, {})}
    return {"symbols": out}
