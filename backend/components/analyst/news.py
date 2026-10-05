from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import time
from backend.configs.settings import settings

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
