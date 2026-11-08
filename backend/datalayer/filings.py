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
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from time import monotonic
from typing import Optional
from urllib.parse import urlparse

import pandas as pd
import requests
from pydantic import BaseModel

from backend.core.market_calendar import is_trading_day, next_trading_day, previous_trading_day
from backend.datalayer import accuracy, news, news_sources
from backend.engine.autorun import in_session
from backend.engine.session import IST
from backend.lab.assumptions import round_trip_return
from backend.llm import llm_service, model_for
from backend.marks import QUOTE_KEY
from backend.prompts import prompt_id

logger = logging.getLogger(__name__)

PDF_HOST = "nsearchives.nseindia.com"
MAX_BYTES, MAX_PAGES, MAX_CHARS = 10 * 1024 * 1024, 6, 8000
MIN_TEXT = 100  # under this a PDF is a scan or empty: there is nothing to read
DOWNLOAD_SECONDS, PARSE_SECONDS = 20, 20
EVENT_TYPES = {"results", "order", "deal", "legal", "regulatory", "management", "capital", "other"}
OUTAGE = news._OUTAGE  # the model never answered: not the filing's fault
COLLECTION = "filing_scores"  # ponytail: no indexes, about 30 rows a day; add (status, published_at) past 100k
PER_PASS, DAILY_CALLS, MAX_ATTEMPTS = 5, 120, 3
LATE_AFTER = timedelta(minutes=30)
WINDOW = (time(9, 15), time(14, 15))  # an entry after 2:15 PM cannot complete its hour before the 3:15 PM square-off
BACKOFF_SECONDS, RECONCILE_SECONDS, LLM_BACKOFF_SECONDS = 300, 300, 60
OUTAGE_GIVE_UP = timedelta(hours=1)
STALL_MINUTES, STALL_ALERT_SECONDS = 20, 3600
OPEN, SQUARE_OFF, BARS_READY = time(9, 15), time(15, 15), time(15, 45)
BENCH = "^NSEI"
HOLD, SHORT_HOLD, MINUTE = timedelta(hours=1), timedelta(minutes=15), timedelta(minutes=1)
BAR_TOLERANCE = timedelta(minutes=5)  # a thin stock may skip a minute; further than this is no price at all
MEASURE_DAYS = 6  # Yahoo keeps 1-minute bars about 7 days
# The pass bar, fixed before any data (spec, "The pass bar"). Do not tune it to the results.
MIN_DIRECTION, MIN_MOVED = 0.5, 0.01
BAR_SIGNALS, BAR_DAYS, BAR_T = 100, 20, 2.0


_PARSER = """
import sys
import pypdfium2
document = pypdfium2.PdfDocument(sys.stdin.buffer.read())
parts = []
for index in range(min(len(document), int(sys.argv[1]))):
    text_page = document[index].get_textpage()
    parts.append(text_page.get_text_range())
sys.stdout.buffer.write("\\n".join(parts).encode("utf-8", "replace"))
"""


def filing_id(item: dict) -> str:
    key = f"{item['symbols'][0]}|{item['title']}|{item['published_at'].isoformat()}"
    return hashlib.sha1(key.encode()).hexdigest()


def allowed_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and parsed.hostname == PDF_HOST


def read_pdf(data: bytes) -> str:
    """The first pages' text, capped; "" for anything that will not parse. In a child process, because PDFium is
    native and not thread-safe: a bad file or two at once would otherwise kill the whole ingest worker."""
    try:
        done = subprocess.run([sys.executable, "-I", "-c", _PARSER, str(MAX_PAGES)], input=data, capture_output=True,
                              timeout=PARSE_SECONDS)
    except subprocess.SubprocessError as exc:
        logger.warning("filing pdf parser stopped: %s", exc)
        return ""
    return done.stdout.decode("utf-8", "replace").strip()[:MAX_CHARS] if done.returncode == 0 else ""


def _download(url: str) -> bytes | None:
    """The body, or None past the size cap."""
    deadline = monotonic() + DOWNLOAD_SECONDS  # `timeout` is per read: a server dripping bytes would never end
    response = requests.get(url, headers=news_sources.UA, timeout=DOWNLOAD_SECONDS, stream=True, allow_redirects=False)
    try:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(64 * 1024):
            body += chunk
            if len(body) > MAX_BYTES or monotonic() > deadline:
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
    return await llm_service.get_completion(user, system_prompt=system, task="news.filing")


def _squeezed(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


async def score_filing(db, doc: dict, ltp: Optional[float], company: str, complete=_standard):
    """The score, OUTAGE when the model is down, None after two invalid answers. A `key_fact` that is
    not in the filing clears the signal: the model described a document it did not read."""
    notes = await news.price_notes(db, [doc], lambda _doc, _symbol: ltp)
    result = await news._ask("score_filing", complete, _FilingScore, symbol=doc["symbols"][0], company=company,
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


def _dated(row: dict) -> bool:
    """`parse_nse` dates a row with no exchange time as now, and the id hashes that date: without
    this every poll would store it as a new filing."""
    try:
        datetime.strptime(row.get("sort_date") or "", "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


async def _claim(db, rows: list[dict], names: dict, now: datetime) -> int:
    """Stores filings not seen before; returns how many were new. The id makes a restart harmless."""
    fresh = 0
    for item in news_sources.parse_nse(list(filter(_dated, rows)), set(names)):
        result = await db[COLLECTION].update_one({"_id": filing_id(item)}, {"$setOnInsert": {
            "symbol": item["symbols"][0], "symbols": item["symbols"], "title": item["title"], "url": item["url"],
            "feed_text": item["content"], "published_at": item["published_at"], "seen_at": now,
            "status": "new", "attempts": 0, "outages": 0}}, upsert=True)
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


async def _failed_attempt(db, doc: dict) -> None:
    attempts = doc["attempts"] + 1
    await db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {
        "attempts": attempts, **({"status": "failed"} if attempts >= MAX_ATTEMPTS else {})}})


async def _process(db, redis, doc: dict, company: str, now: datetime, began: float) -> bool:
    """One filing. False when the model is down, so the pass stops and nothing is held against the filing."""
    coll = db[COLLECTION]
    if "pdf_ok" in doc:  # read on an earlier try
        text, pdf_ok = doc["text"], doc["pdf_ok"]
    else:
        text, pdf_ok = await fetch_text(doc.get("url") or "")
        text = text if pdf_ok else doc.get("feed_text") or ""
        await coll.update_one({"_id": doc["_id"]}, {"$set": {"text": text, "pdf_ok": pdf_ok}})

    async def counted(system: str, user: str) -> str:
        key = f"filings:calls:{_ist_day(now)}"
        await redis.incrby(key, 1)
        await redis.expire(key, 2 * 86_400)
        return await _standard(system, user)

    raw = await redis.get(QUOTE_KEY.format(doc["symbol"]))
    ltp = json.loads(raw).get("ltp") if raw else None
    score = await score_filing(db, {**doc, "text": text}, ltp, company, complete=counted)
    if score is OUTAGE:
        await coll.update_one({"_id": doc["_id"]}, {"$inc": {"outages": 1}})  # behind the others, so a refused filing blocks none
        await redis.set("filings:llm_backoff", "1", ex=LLM_BACKOFF_SECONDS)
        return False
    if score is None:
        await _failed_attempt(db, doc)
        return True
    # The signal exists only now: an entry from the start of the pass would precede it.
    done = now + timedelta(seconds=monotonic() - began)
    await coll.update_one({"_id": doc["_id"]}, {"$set": {
        "status": "scored", "score": score, "model": await model_for("standard"),
        "prompt": prompt_id("score_filing"), "scored_at": done,
        "late": done - _aware(doc["published_at"]) > LATE_AFTER, "in_window": in_window(done)}})
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

    now, began = now or datetime.now(timezone.utc), monotonic()
    names, _ = await news.followed(db)
    await _poll_feed(db, redis, names, now)
    coll = db[COLLECTION]
    # A filing the provider keeps refusing is past 30 minutes by then, so it could not count anyway.
    await coll.update_many({"status": "new", "outages": {"$gte": 1}, "seen_at": {"$lte": now - OUTAGE_GIVE_UP}},
                           {"$set": {"status": "failed"}})
    if await feature_enabled("news", db) and not await redis.get("filings:llm_backoff"):
        docs = await coll.find({"status": "new"}).sort([("outages", 1), ("published_at", 1)]).limit(PER_PASS).to_list(length=None)
        for doc in docs:
            # A filing may take two calls: its answer and one retry.
            if int(await redis.get(f"filings:calls:{_ist_day(now)}") or 0) + 2 > DAILY_CALLS:
                break
            try:
                if not await _process(db, redis, doc, names.get(doc["symbol"], doc["symbol"]), now, began):
                    break
            except Exception as exc:
                logger.warning("filing %s failed: %s", doc["_id"], exc)
                await _failed_attempt(db, doc)
    await _stall_alert(db, redis, now)


def entry_time(scored_at: datetime) -> pd.Timestamp:
    """The first minute a trade could start, naive IST as the bars are: the next minute in session,
    else the next session's open."""
    local = _aware(scored_at).astimezone(IST)
    day = local.date()
    if is_trading_day(day) and local.time() < OPEN:
        return pd.Timestamp.combine(day, OPEN)
    if is_trading_day(day) and local.time() < SQUARE_OFF:
        return pd.Timestamp(local.replace(tzinfo=None, second=0, microsecond=0)) + pd.Timedelta(minutes=1)
    return pd.Timestamp.combine(next_trading_day(day), OPEN)


def _entry_price(frame: pd.DataFrame, at: pd.Timestamp) -> Optional[float]:
    window = frame.loc[at:at + BAR_TOLERANCE, "open"].dropna()
    return float(window.iloc[0]) if len(window) else None


def _close_at(frame: pd.DataFrame, at: pd.Timestamp) -> Optional[float]:
    """The last price before minute `at`: the bar labelled 10:40 closes at 10:41."""
    window = frame.loc[at - BAR_TOLERANCE - MINUTE:at - MINUTE, "close"].dropna()
    return float(window.iloc[-1]) if len(window) else None


def _prev_close(frame: pd.DataFrame, day) -> Optional[float]:
    """The previous session's last price, from the same raw bars as the entry, so the two share a basis.
    ponytail: on an ex-dividend day the drop reads as a move; rare, and small against the 1% test."""
    closes = frame.loc[frame.index.date == previous_trading_day(day), "close"]
    return float(closes.iloc[-1]) if len(closes) else None


def _moved_by(frame: pd.DataFrame, at: pd.Timestamp) -> Optional[float]:
    """The move since the last close, as a trader could see it before entering; at the open, the gap."""
    prev = _prev_close(frame, at.date())
    now_price = _entry_price(frame, at) if at.time() == OPEN else _close_at(frame, at)
    return now_price / prev - 1 if prev and now_price else None


def measure_row(row: dict, stock: pd.DataFrame, nifty: pd.DataFrame) -> Optional[dict]:
    """Prices at entry and each horizon, the move before entry net of Nifty, and the hypothetical
    1-hour trade after charges. None when there is no entry price: unmeasured, never flat."""
    at = entry_time(row["scored_at"])
    entry = _entry_price(stock, at)
    if entry is None:
        return None
    square_off = pd.Timestamp.combine(at.date(), SQUARE_OFF)
    own, bench = _moved_by(stock, at), _moved_by(nifty, at)
    moved = own - bench if own is not None and bench is not None else None
    px_1h = _close_at(stock, at + HOLD) if at + HOLD <= square_off else None
    direction = (row.get("score") or {}).get("direction") or 0
    net = None
    if px_1h is not None and direction:
        net = round_trip_return(entry, px_1h, product="MIS") if direction > 0 else round_trip_return(px_1h, entry, product="MIS")
    return {"entry_at": at.isoformat(), "px_entry": entry, "moved_net": moved,
            "px_15m": _close_at(stock, at + SHORT_HOLD) if at + SHORT_HOLD <= square_off else None,
            "px_1h": px_1h, "px_close": _close_at(stock, square_off), "net_1h": net}


def _download_minutes(symbols: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    names = {(s if s.startswith("^") else f"{s}.NS"): s for s in {*symbols, BENCH}}
    frame = yf.download(sorted(names), period="7d", interval="1m", progress=False, threads=True,
                        ignore_tz=True, auto_adjust=False)
    if "Open" not in frame:
        return {}
    return {symbol: pd.DataFrame({"open": frame["Open"][ticker], "close": frame["Close"][ticker]}).dropna()
            for ticker, symbol in names.items() if ticker in frame["Open"]}


async def _minute_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    try:
        return await asyncio.to_thread(_download_minutes, symbols)
    except Exception as exc:
        logger.warning("filing minute bars failed: %s", exc)
        return {}


async def measure_loop(db, redis, now: Optional[datetime] = None) -> None:
    """After each close, the day's scored filings get their prices. It reads bars after the fact, so a
    restart loses nothing; a filing whose bars never arrive ends unmeasured, with no figure."""
    now = now or datetime.now(timezone.utc)
    local = pd.Timestamp(now.astimezone(IST).replace(tzinfo=None))
    due = []
    async for row in db[COLLECTION].find({"status": "scored", "measured": {"$exists": False}}):
        at = entry_time(row["scored_at"])
        if local >= pd.Timestamp.combine(at.date(), BARS_READY):
            due.append((row, at))
    if not due:
        return
    frames = await _minute_bars(sorted({row["symbol"] for row, _ in due}))
    for row, at in due:
        stock, nifty = frames.get(row["symbol"]), frames.get(BENCH)
        fields = measure_row(row, stock, nifty) if stock is not None and nifty is not None else None
        hour_possible = at + HOLD <= pd.Timestamp.combine(at.date(), SQUARE_OFF)
        complete = bool(fields) and fields["moved_net"] is not None and (fields["px_1h"] is not None or not hour_possible)
        expired = local - at > pd.Timedelta(days=MEASURE_DAYS)
        if complete or expired:  # partial bars are read again while Yahoo still has them
            await db[COLLECTION].update_one({"_id": row["_id"]}, {"$set": {**(fields or {}), "measured": complete}})


def _usable(row: dict) -> bool:
    """Measured, read from the PDF, on time and inside the window, with a real signal."""
    score = row.get("score") or {}
    return (row.get("net_1h") is not None and bool(row.get("pdf_ok")) and not row.get("late") and bool(row.get("in_window"))
            and bool(score.get("key_fact_ok")) and abs(score.get("direction") or 0) >= MIN_DIRECTION)


def primary_signals(rows: list[dict]) -> list[dict]:
    """The one rule under test: the price already moved its way. First per symbol per day, since a revised
    filing is not a second piece of evidence."""
    seen, out = set(), []
    for row in sorted(filter(_usable, rows), key=lambda r: _aware(r["scored_at"])):
        moved, direction = row.get("moved_net"), row["score"]["direction"]
        if moved is None or moved * (1 if direction > 0 else -1) < MIN_MOVED:
            continue
        key = (row["symbol"], _ist_day(_aware(row["scored_at"])))
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def _stats(rows: list[dict]) -> dict:
    points = [(_ist_day(_aware(r["scored_at"])), r["net_1h"], r["net_1h"] > 0) for r in rows]
    return accuracy._stats(points) if points else {"n": 0, "days": 0, "hit": None, "mean": None, "t": None, "thin": True}


def _standing(rows: list[dict]) -> dict:
    s = _stats(rows)
    return {**s, "passes": s["n"] >= BAR_SIGNALS and s["days"] >= BAR_DAYS and (s["mean"] or 0) > 0 and (s["t"] or 0) >= BAR_T}


def bar(rows: list[dict]) -> dict:
    signals = primary_signals(rows)
    return {**_standing(signals), "long_only": _standing([r for r in signals if r["score"]["direction"] > 0])}


def exploratory(rows: list[dict]) -> list[dict]:
    """Splits to look at, never to pass: a promising one becomes a new rule and counts from zero on new data."""
    def moved_bucket(row):
        moved = row.get("moved_net")
        if moved is None:
            return "unknown"
        signed = moved * (1 if row["score"]["direction"] > 0 else -1)
        return ">=3%" if signed >= 0.03 else "1-3%" if signed >= MIN_MOVED else "<1%"

    def priced_bucket(row):
        priced = row["score"].get("priced_in")
        return "unknown" if priced is None else "priced" if priced >= accuracy.PRICED else "fresh"

    splits = {"event_type": lambda r: r["score"].get("event_type") or "other",
              "impact": lambda r: accuracy.impact_bucket(r["score"].get("impact") or 0),
              "priced_in": priced_bucket, "moved": moved_bucket}
    usable = [r for r in rows if _usable(r)]
    cells = []
    for split, key_of in splits.items():
        groups: dict[str, list] = {}
        for row in usable:
            groups.setdefault(key_of(row), []).append(row)
        cells += [{"split": split, "key": key, **_stats(part)} for key, part in sorted(groups.items())]
    return cells


async def report(db, redis, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = await db[COLLECTION].find({}, {"text": 0, "feed_text": 0}).to_list(length=None)
    scored = [r for r in rows if r.get("status") == "scored"]
    lags = sorted((_aware(r["scored_at"]) - _aware(r["published_at"])).total_seconds() / 60
                  for r in scored if r.get("in_window") and not r.get("late"))
    gaps = await redis.get(f"filings:gaps:{_ist_day(now)}") if redis is not None else None
    return {"bar": bar(rows), "exploratory": exploratory(rows), "health": {
        "total": len(rows), "waiting": sum(r.get("status") == "new" for r in rows),
        "failed": sum(r.get("status") == "failed" for r in rows),
        "pdf_failed": sum(not r.get("pdf_ok") for r in scored),
        "key_fact_rejected": sum(not (r.get("score") or {}).get("key_fact_ok") for r in scored),
        "unmeasured": sum(r.get("measured") is False for r in rows),
        "median_lag_minutes": round(lags[len(lags) // 2], 1) if lags else None,
        "gaps_today": int(gaps or 0)}}
