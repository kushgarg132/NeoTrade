"""The filing lane: read NSE filings fast, score them from their own text and record what the
price then did. It places no orders and feeds nothing: `filing_scores` is read only by its report
(spec docs/superpowers/specs/2026-11-03-filing-lane-design.md).

The announcements feed returns 20 rows, or a whole day's with `from_date` and `to_date`. Filing
text is untrusted: it is fetched from one host, capped, parsed in memory, and treated as data.
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import pypdfium2
import requests
from pydantic import BaseModel

from backend.core.market_calendar import is_trading_day
from backend.datalayer import news, news_sources
from backend.engine.autorun import in_session
from backend.engine.session import IST
from backend.llm import llm_service, model_for
from backend.marks import QUOTE_KEY
from backend.prompts import prompt_id

logger = logging.getLogger(__name__)

PDF_HOST = "nsearchives.nseindia.com"
MAX_BYTES, MAX_PAGES, MAX_CHARS = 10 * 1024 * 1024, 6, 8000
MIN_TEXT = 100  # under this a PDF is a scan or empty: there is nothing to read
DOWNLOAD_SECONDS = 20
EVENT_TYPES = {"results", "order", "deal", "legal", "regulatory", "management", "capital", "other"}
OUTAGE = news._OUTAGE  # the model never answered: not the filing's fault
COLLECTION = "filing_scores"  # ponytail: no indexes, about 30 rows a day; add (status, published_at) past 100k
PER_PASS, DAILY_CALLS, MAX_ATTEMPTS = 5, 120, 3
LATE_AFTER = timedelta(minutes=30)
WINDOW = (time(9, 15), time(14, 15))  # an entry after 2:15 PM cannot complete its hour before the 3:15 PM square-off
BACKOFF_SECONDS, RECONCILE_SECONDS = 300, 300
STALL_MINUTES, STALL_ALERT_SECONDS = 20, 3600


def filing_id(item: dict) -> str:
    key = f"{item['symbols'][0]}|{item['title']}|{item['published_at'].isoformat()}"
    return hashlib.sha1(key.encode()).hexdigest()


def allowed_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and parsed.hostname == PDF_HOST


def read_pdf(data: bytes) -> str:
    """The first pages' text, capped; "" for anything that will not parse."""
    try:
        document = pypdfium2.PdfDocument(data)
    except Exception:
        return ""
    try:
        parts = []
        for index in range(min(len(document), MAX_PAGES)):
            page = document[index]
            text_page = page.get_textpage()
            parts.append(text_page.get_text_range())
            text_page.close()
            page.close()
        return "\n".join(parts).strip()[:MAX_CHARS]
    except Exception as exc:
        logger.warning("filing pdf unreadable: %s", exc)
        return ""
    finally:
        document.close()


def _download(url: str) -> bytes | None:
    """The body, or None past the size cap."""
    response = requests.get(url, headers=news_sources.UA, timeout=DOWNLOAD_SECONDS, stream=True)
    try:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(64 * 1024):
            body += chunk
            if len(body) > MAX_BYTES:
                return None
        return bytes(body)
    finally:
        response.close()


async def fetch_text(url: str) -> tuple[str, bool]:
    """(text, pdf_ok). Never raises: a filing that cannot be read still gets scored on the feed's text."""
    if not allowed_url(url):
        return "", False
    try:
        data = await asyncio.to_thread(_download, url)
    except Exception as exc:
        logger.warning("filing pdf not fetched: %s", exc)
        return "", False
    if not data or not data.startswith(b"%PDF"):
        return "", False
    text = await asyncio.to_thread(read_pdf, data)
    return text, len(text) >= MIN_TEXT


class _FilingScore(BaseModel):
    event_type: str = "other"
    direction: float = 0.0
    impact: float = 1.0
    priced_in: Optional[float] = None
    key_fact: str = ""


async def _standard(system: str, user: str) -> str:
    return await llm_service.get_completion(user, system_prompt=system, tier="standard", feature="news")


def _squeezed(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


async def score_filing(db, doc: dict, ltp: Optional[float], company: str):
    """The score, OUTAGE when the model is down, None after two invalid answers. A `key_fact` that is
    not in the filing clears the signal: the model described a document it did not read."""
    notes = await news.price_notes(db, [doc], lambda _doc, _symbol: ltp)
    result = await news._ask("score_filing", _standard, _FilingScore, symbol=doc["symbols"][0], company=company,
                             title=doc["title"], price=notes.get(doc["_id"], "not available"), text=doc.get("text") or "")
    if result is OUTAGE or result is None:
        return result
    fact = _squeezed(result.key_fact)
    fact_ok = bool(fact) and fact in _squeezed(doc.get("text"))
    return {"event_type": result.event_type if result.event_type in EVENT_TYPES else "other",
            "direction": max(-1.0, min(1.0, result.direction)) if fact_ok else 0.0,
            "impact": max(0.0, min(10.0, result.impact)) if fact_ok else 0.0,
            "priced_in": None if result.priced_in is None else max(0.0, min(1.0, result.priced_in)),
            "key_fact": result.key_fact[:300], "key_fact_ok": fact_ok}


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _ist_day(now: datetime) -> str:
    return now.astimezone(IST).date().isoformat()


def in_window(at: datetime) -> bool:
    local = _aware(at).astimezone(IST)
    return is_trading_day(local.date()) and WINDOW[0] <= local.time() <= WINDOW[1]


async def _send_admins(db, text: str) -> None:
    from backend.system.data_quality import _send_admins as send

    await send(db, text)


async def _fetch_rows(url: str) -> list[dict]:
    rows = (await asyncio.to_thread(news_sources._get, url)).json()
    return rows if isinstance(rows, list) else []


async def _claim(db, rows: list[dict], names: dict, now: datetime) -> int:
    """Stores filings not seen before; returns how many were new. The id makes a restart harmless."""
    fresh = 0
    for item in news_sources.parse_nse(rows, set(names)):
        result = await db[COLLECTION].update_one({"_id": filing_id(item)}, {"$setOnInsert": {
            "symbol": item["symbols"][0], "symbols": item["symbols"], "title": item["title"], "url": item["url"],
            "feed_text": item["content"], "published_at": item["published_at"], "seen_at": now,
            "status": "new", "attempts": 0}}, upsert=True)
        fresh += result.upserted_id is not None
    return fresh


async def _poll_feed(db, redis, names: dict, now: datetime) -> None:
    if await redis.get("filings:backoff"):
        return
    try:
        await _claim(db, await _fetch_rows(news_sources.NSE_ANNOUNCEMENTS), names, now)
        if await redis.set("filings:reconcile", "1", nx=True, ex=RECONCILE_SECONDS):
            # The short feed holds 20 rows of every company on the exchange, so a busy minute can push one out.
            # ponytail: a restart's first reconcile also counts the day so far; read the count as an upper bound.
            day = now.astimezone(IST).strftime("%d-%m-%Y")
            rows = await _fetch_rows(f"{news_sources.NSE_ANNOUNCEMENTS}&from_date={day}&to_date={day}")
            missed = await _claim(db, rows, names, now)
            if missed:
                key = f"filings:gaps:{_ist_day(now)}"
                await redis.set(key, str(int(await redis.get(key) or 0) + missed), ex=40 * 86_400)
        await redis.set("filings:last_ok", str(now.timestamp()), ex=7 * 86_400)
    except Exception as exc:
        logger.warning("filings feed failed, backing off: %s", exc)
        await redis.set("filings:backoff", "1", ex=BACKOFF_SECONDS)


async def _process(db, redis, doc: dict, company: str, now: datetime) -> bool:
    """One filing. False when the model is down, so the pass stops and nothing is held against the filing."""
    text, pdf_ok = await fetch_text(doc.get("url") or "")
    text = text if pdf_ok else doc.get("feed_text") or ""
    raw = await redis.get(QUOTE_KEY.format(doc["symbol"]))
    ltp = json.loads(raw).get("ltp") if raw else None
    score = await score_filing(db, {**doc, "text": text}, ltp, company)
    if score is OUTAGE:
        return False
    day, coll = _ist_day(now), db[COLLECTION]
    if score is None:
        attempts = doc["attempts"] + 1
        await coll.update_one({"_id": doc["_id"]}, {"$set": {
            "attempts": attempts, "attempted_on": day, **({"status": "failed"} if attempts >= MAX_ATTEMPTS else {})}})
        return True
    await coll.update_one({"_id": doc["_id"]}, {"$set": {
        "status": "scored", "pdf_ok": pdf_ok, "text": text, "score": score, "model": await model_for("standard"),
        "prompt": prompt_id("score_filing"), "scored_at": now, "attempted_on": day,
        "late": now - _aware(doc["published_at"]) > LATE_AFTER, "in_window": in_window(now)}})
    return True


async def _stall_alert(db, redis, now: datetime) -> None:
    if not in_session(now):
        return
    cutoff = now - timedelta(minutes=STALL_MINUTES)
    last_ok = await redis.get("filings:last_ok")
    waiting = await db[COLLECTION].count_documents({"status": "new", "seen_at": {"$lte": cutoff}})
    why = f"{waiting} filing(s) waiting over {STALL_MINUTES} minutes" if waiting else (
        f"filings feed not read for over {STALL_MINUTES} minutes"
        if last_ok and float(last_ok) < cutoff.timestamp() else None)
    if why and await redis.set("filings:stall_alert", "1", nx=True, ex=STALL_ALERT_SECONDS):
        await _send_admins(db, f"⚠️ NeoTrade filing lane\n• {why}")


async def poll_loop(db, redis, now: Optional[datetime] = None) -> None:
    """Every 20 seconds on the ingest leader: claim new filings, then read and score a few, oldest first."""
    from backend.app_settings import feature_enabled

    now = now or datetime.now(timezone.utc)
    names, _ = await news.followed(db)
    await _poll_feed(db, redis, names, now)
    if await feature_enabled("news", db):
        room = DAILY_CALLS - await db[COLLECTION].count_documents({"attempted_on": _ist_day(now)})
        docs = await db[COLLECTION].find({"status": "new"}).sort("published_at", 1).limit(max(0, min(PER_PASS, room))).to_list(length=None) if room > 0 else []
        for doc in docs:
            if not await _process(db, redis, doc, names.get(doc["symbol"], doc["symbol"]), now):
                break
    await _stall_alert(db, redis, now)
