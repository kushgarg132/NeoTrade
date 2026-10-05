"""Where news comes from: RSS feeds, Google News searches, GDELT and NSE
filings. Every fetcher returns plain dicts:

    {title, url, source, published_at (aware UTC), content, feed, scope_hint, symbols}

`scope_hint` is the feed's own beat (COMPANY / SECTOR / MARKET / MACRO /
GLOBAL); triage decides the real scope. Adding a feed is one line in FEEDS.
Every fetch is best-effort: a failing source logs and returns [].
"""

import asyncio
import csv
import logging
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
MAX_AGE = timedelta(days=3)
GOOGLE = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"

# (name, url, scope_hint, every N seconds)
FEEDS = [
    ("et_markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "MARKET", 60),
    ("et_economy", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms", "MACRO", 120),
    ("mc_latest", "https://www.moneycontrol.com/rss/latestnews.xml", "MARKET", 60),
    ("mc_reports", "https://www.moneycontrol.com/rss/marketreports.xml", "MARKET", 300),
    ("mint_markets", "https://www.livemint.com/rss/markets", "MARKET", 60),
    ("mint_economy", "https://www.livemint.com/rss/economy", "MACRO", 120),
    ("rbi", "https://www.rbi.org.in/pressreleases_rss.xml", "MACRO", 300),
    ("sebi", "https://www.sebi.gov.in/sebirss.xml", "MACRO", 300),
    ("pib", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3", "MACRO", 300),
    ("cnbc_top", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "GLOBAL", 120),
    ("cnbc_world", "https://www.cnbc.com/id/100727362/device/rss/rss.html", "GLOBAL", 120),
    ("cnbc_economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html", "GLOBAL", 120),
    ("bbc_business", "https://feeds.bbci.co.uk/news/business/rss.xml", "GLOBAL", 300),
    ("bbc_world", "https://feeds.bbci.co.uk/news/world/rss.xml", "GLOBAL", 300),
    ("gnews_business", "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en", "MARKET", 120),
    ("gnews_world", "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en", "GLOBAL", 120),
    ("gnews_india_market", GOOGLE.format(q=quote_plus("Sensex Nifty stock market when:1h")), "MARKET", 120),
    ("gnews_india_macro", GOOGLE.format(q=quote_plus("RBI rupee crude oil FII markets when:1h")), "MACRO", 120),
]

GDELT = ("https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist&format=json&timespan=1h&maxrecords=75&query="
         + quote_plus('(oil OR crude OR OPEC OR sanctions OR tariff OR "Federal Reserve" OR "interest rate" OR war '
                      'OR inflation OR recession OR China OR election) sourcelang:english'))
GDELT_SECONDS = 300

NSE_ANNOUNCEMENTS = "https://www.nseindia.com/api/corporate-announcements?index=equities"
NSE_SECONDS = 60
# Routine filings that never move a price.
NSE_SKIP = ("newspaper publication", "trading window", "certificate under", "compliance officer",
            "loss of share", "duplicate share", "shareholders meeting", "esop", "esos")

SECTOR_SECONDS = 15 * 60
SYMBOL_PRIORITY_SECONDS = 5 * 60
SYMBOLS_PER_PASS = 10
GOOGLE_SEARCH_LIMIT = 8

_UNIVERSE_FILE = Path(__file__).parents[1] / "factor" / "nifty200.csv"
_last: dict[str, float] = {}  # source key -> last fetch (unix)
_symbol_cursor = 0


def universe_rows() -> list[dict]:
    """Nifty 200: symbol, company name, NSE industry (our sector names)."""
    with _UNIVERSE_FILE.open() as f:
        return [{"symbol": r["Symbol"].strip(), "name": r["Company Name"].strip(), "sector": r["Industry"].strip()}
                for r in csv.DictReader(f) if r.get("Series", "EQ").strip() == "EQ"]


def sectors() -> list[str]:
    return sorted({r["sector"] for r in universe_rows()})


def _due(key: str, every: float, now: float) -> bool:
    if now - _last.get(key, 0) < every:
        return False
    _last[key] = now
    return True


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _text(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)[:1000]


def parse_rss(xml: bytes, feed: str, scope_hint: str, symbols=()) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - MAX_AGE
    items = []
    for item in BeautifulSoup(xml, features="xml").find_all("item"):
        title = item.title.get_text(strip=True) if item.title else ""
        if not title:
            continue
        try:
            published = _aware(parsedate_to_datetime(item.pubDate.get_text(strip=True)))
        except Exception:
            published = datetime.now(timezone.utc)
        if published < cutoff:
            continue
        items.append({
            "title": title,
            "url": item.link.get_text(strip=True) if item.link else "",
            "source": item.source.get_text(strip=True) if item.source else feed,
            "published_at": published,
            "content": _text(item.description.get_text() if item.description else ""),
            "feed": feed, "scope_hint": scope_hint, "symbols": list(symbols),
        })
    return items


def _get(url: str, **kw) -> requests.Response:
    response = requests.get(url, headers=UA, timeout=15, **kw)
    response.raise_for_status()
    return response


async def fetch_rss(url: str, feed: str, scope_hint: str, symbols=(), limit: int = 100) -> list[dict]:
    """`limit`: newest items kept. A Google search returns up to 100 mostly
    old or tangential results; its top few are what matter."""
    try:
        response = await asyncio.to_thread(_get, url)
        items = parse_rss(response.content, feed, scope_hint, symbols)
        return sorted(items, key=lambda i: i["published_at"], reverse=True)[:limit]
    except Exception as exc:
        logger.warning("news feed %s failed: %s", feed, exc)
        return []


async def fetch_gdelt() -> list[dict]:
    try:
        data = (await asyncio.to_thread(_get, GDELT)).json()
    except Exception as exc:  # also the 429 "one request every 5 seconds" text body
        logger.warning("news feed gdelt failed: %s", exc)
        return []
    items = []
    for a in data.get("articles", []):
        try:
            published = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            published = datetime.now(timezone.utc)
        if a.get("title"):
            items.append({"title": a["title"], "url": a.get("url", ""), "source": a.get("domain", "gdelt"),
                          "published_at": published, "content": "", "feed": "gdelt", "scope_hint": "GLOBAL",
                          "symbols": []})
    return items


def parse_nse(rows: list[dict], symbols: set[str]) -> list[dict]:
    items = []
    for r in rows:
        symbol, desc = r.get("symbol"), (r.get("desc") or "")
        if symbol not in symbols or any(s in desc.lower() for s in NSE_SKIP):
            continue
        try:
            published = datetime.strptime(r["sort_date"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone(timedelta(hours=5, minutes=30))).astimezone(timezone.utc)
        except (KeyError, ValueError):
            published = datetime.now(timezone.utc)
        items.append({
            "title": f"{r.get('sm_name') or symbol}: {desc}", "url": r.get("attchmntFile") or "",
            "source": "NSE filing", "published_at": published, "content": (r.get("attchmntText") or "")[:1000],
            "feed": "nse", "scope_hint": "COMPANY", "symbols": [symbol],
        })
    return items


async def fetch_nse(symbols: set[str]) -> list[dict]:
    try:
        rows = (await asyncio.to_thread(_get, NSE_ANNOUNCEMENTS)).json()
    except Exception as exc:
        logger.warning("news feed nse failed: %s", exc)
        return []
    return parse_nse(rows if isinstance(rows, list) else [], symbols)


def _symbol_queries(priority: set[str], names: dict[str, str], now: float) -> list[str]:
    """Up to SYMBOLS_PER_PASS symbols: held/watched ones not searched in
    SYMBOL_PRIORITY_SECONDS first, then the Nifty 200 round-robin."""
    global _symbol_cursor
    picked = [s for s in sorted(priority) if now - _last.get(f"sym:{s}", 0) >= SYMBOL_PRIORITY_SECONDS]
    picked = picked[:SYMBOLS_PER_PASS]
    rest = sorted(set(names) - priority)
    while len(picked) < SYMBOLS_PER_PASS and rest:
        picked.append(rest[_symbol_cursor % len(rest)])
        _symbol_cursor += 1
        if _symbol_cursor % len(rest) == 0:
            break
    for s in picked:
        _last[f"sym:{s}"] = now
    return picked


async def poll(priority: set[str], names: dict[str, str]) -> list[dict]:
    """Every source that is due. `names` is symbol -> company name for every
    symbol we follow (Nifty 200 + `priority`, the held/watched ones)."""
    now = time.time()
    jobs = [fetch_rss(url, name, scope, ()) for name, url, scope, every in FEEDS if _due(name, every, now)]
    if _due("gdelt", GDELT_SECONDS, now):
        jobs.append(fetch_gdelt())
    if _due("nse", NSE_SECONDS, now):
        jobs.append(fetch_nse(set(names)))
    if _due("sectors", SECTOR_SECONDS, now):
        jobs += [fetch_rss(GOOGLE.format(q=quote_plus(f'India "{s}" sector stocks when:1d')), "gnews_sector", "SECTOR", limit=GOOGLE_SEARCH_LIMIT)
                 for s in sectors()]
    for symbol in _symbol_queries(priority, names, now):
        query = f'"{names.get(symbol) or symbol}" share news when:2d'
        jobs.append(fetch_rss(GOOGLE.format(q=quote_plus(query)), "gnews_symbol", "COMPANY", (symbol,), GOOGLE_SEARCH_LIMIT))
    batches = await asyncio.gather(*jobs)
    return [item for batch in batches for item in batch]
