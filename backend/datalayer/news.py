"""The news pipeline: store every market-relevant item, score what it moves,
and keep per-symbol, per-sector and market-wide sentiment fresh.

    poll (60s)     sources -> dedupe into Mongo `news_items` (status NEW)
    process (5min) NEW -> triage (ONE fast call, up to 150 headlines) -> TRIAGED or IRRELEVANT
                   TRIAGED -> score (ONE deep call, up to 40 items, NEWS_LLM_CALLS_PER_DAY)
                           -> SCORED with impacts[] on market/sectors/symbols
                   -> aggregate -> Redis sentiment:{SYM}, sector_sentiment:{S},
                      market:sentiment, analyst_verdict:{SYM}

`sentiment:{SYM}` is what the engine and scans already read for the AI half
of conviction (backend/ai/sentiment.py): 0.6 * company + 0.25 * the stock's
sector + 0.15 * the Indian market, each the impact- and recency-weighted
mean of the impacts on that target over WINDOW. Each impact is first scaled
by its item's learned theme weight (backend/datalayer/outcomes.py, 0.5-1.5). It is still the single
ai_score input composite.py caps at AI_CAP, not a second conviction formula.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError

from backend.ai.sentiment import weighted_sentiment
from backend.components.analyst.agent import _extract_json
from backend.components.analyst.news import _title_key
from backend.configs.settings import settings
from backend.datalayer import news_sources
from backend.datalayer.prices import priority_symbols
from backend.llm import llm_service
from backend.prompts import render
from backend.strategies.longterm.analyst_verdict import MATERIALITY_THRESHOLD

logger = logging.getLogger(__name__)

COLLECTION = "news_items"
NEW, TRIAGED, SCORED, IRRELEVANT, FAILED, STALE = "NEW", "TRIAGED", "SCORED", "IRRELEVANT", "FAILED", "STALE"
SCOPES = ("COMPANY", "SECTOR", "MARKET", "MACRO", "GLOBAL")
MARKET_TARGET = "INDIA"

IRRELEVANT_TTL = timedelta(days=7)
RELEVANT_TTL = timedelta(days=730)  # kept as learning data (news -> price outcomes)
MAX_ATTEMPTS = 3
# LLM calls are the cost, so each pass makes at most one call per stage
# over everything that piled up since the last pass: news reaches the
# scores within ~PROCESS_SECONDS instead of seconds, for ~2 calls a pass.
TRIAGE_BATCH, TRIAGE_CALLS_PER_PASS = 150, 1
SCORE_BATCH = 40
# A deep call costs the same for 3 items as for 40, so scoring waits until a
# batch is worth it -- unless a held/watched name is waiting or the oldest
# item has waited SCORE_HOLD (market-wide news is at most one pass later).
SCORE_MIN_ITEMS = 20
SCORE_HOLD = timedelta(minutes=10)
SCORE_MAX_AGE = timedelta(days=3)  # older unscored items are not worth an LLM call
PROCESS_SECONDS = 5 * 60
# Outside the session (and its 45-min run-up) nothing trades on a score, so
# news is triaged and scored hourly in fuller batches instead of every pass.
OFF_PROCESS_SECONDS = 60 * 60
OFF_TRIAGE_CALLS = 2  # ~110 headlines/hour off-hours, one batch is usually enough

WINDOW = timedelta(days=60)
VERDICT_WINDOW = timedelta(days=14)
COMPANY_WEIGHT, SECTOR_WEIGHT, MARKET_WEIGHT = 0.6, 0.25, 0.15
SENTIMENT_TTL_SECONDS = 24 * 3600
VERDICT_TTL_SECONDS = 25 * 3600
AGGREGATE_EVERY_SECONDS = 10 * 60


# ---------------------------------------------------------------- following


def short_name(name: str) -> str:
    """'Reliance Industries Ltd.' -> 'Reliance Industries'."""
    return re.sub(r"\s+(ltd\.?|limited)$", "", name.strip(), flags=re.I).strip()


async def followed(db) -> tuple[dict[str, str], dict[str, str]]:
    """(symbol -> short company name, symbol -> sector) for the Nifty 200
    plus every held or watched symbol (those may have no sector)."""
    names, sector_of = {}, {}
    for row in news_sources.universe_rows():
        names[row["symbol"]] = short_name(row["name"])
        sector_of[row["symbol"]] = row["sector"]
    for symbol in await priority_symbols(db) - names.keys():
        doc = await db["instruments"].find_one({"exchange": "NSE", "tradingsymbol": symbol}, {"name": 1})
        names[symbol] = short_name((doc or {}).get("name") or symbol)
    return names, sector_of


# ------------------------------------------------------------------ tagging

# First words too common, or too often another company or thing, to stand
# for one followed company on their own ("Supreme Court", "Asian markets",
# "Federal Reserve", Oracle Corp, Hyundai Korea...).
_GENERIC = {"state", "power", "general", "national", "indian", "india", "united", "bharat", "union", "central",
            "global", "life", "new", "hindustan", "bank", "info", "max", "oil", "gas", "steel", "motor", "motors",
            "aditya", "asian", "avenue", "container", "federal", "indus", "multi", "oracle", "persistent", "premier",
            "solar", "supreme", "punjab", "eternal", "hitachi", "hyundai", "bosch", "varun", "vishal", "phoenix",
            "ashok", "kalyan", "cochin", "jindal", "mankind", "nestle", "colgate", "oberoi", "prestige"}
# Names that are also something else in market news (BSE the exchange and
# its Sensex): tagged only by filings and their own Google search.
_NO_ALIAS = {"BSE"}


def build_aliases(names: dict[str, str]) -> list[tuple[re.Pattern, str]]:
    """Regexes that find a company in a headline: its short name, its first
    word when no other followed company shares it, and its ticker (matched
    case-sensitively, 3+ characters)."""
    firsts = defaultdict(set)
    for symbol, name in names.items():
        firsts[name.split()[0].lower()].add(symbol)
    aliases = []
    for symbol, name in names.items():
        if symbol in _NO_ALIAS:
            continue
        words = {name.lower()}
        first = name.split()[0].lower()
        if len(firsts[first]) == 1 and len(first) >= 5 and first not in _GENERIC:
            words.add(first)
        for word in words:
            # "Reserve Bank of India" is not Bank of India.
            guard = r"(?<!reserve )" if word.startswith("bank") else ""
            aliases.append((re.compile(guard + r"\b" + re.escape(word) + r"\b", re.I), symbol))
        if len(symbol) >= 3:
            aliases.append((re.compile(r"\b" + re.escape(symbol) + r"\b"), symbol))
    return aliases


def tag(text: str, aliases) -> list[str]:
    return sorted({symbol for pattern, symbol in aliases if pattern.search(text)})


# ------------------------------------------------------------------- ingest


def item_id(title: str) -> str:
    """One document per story, however many sources carry it."""
    return hashlib.sha1(_title_key(title).encode()).hexdigest()


async def ensure_indexes(db) -> None:
    coll = db[COLLECTION]
    await coll.create_index("expire_at", expireAfterSeconds=0)
    await coll.create_index([("status", 1), ("fetched_at", 1)])
    await coll.create_index([("impacts.target", 1), ("published_at", -1)])
    await coll.create_index([("symbols", 1), ("published_at", -1)])
    await coll.create_index([("published_at", -1)])
    await db["news_outcomes"].create_index("base_at")


async def store(db, items: list[dict], aliases, now: Optional[datetime] = None) -> int:
    """Upserts `items`; returns how many were new. A story seen again only
    gains the new feed and symbols. NSE filings skip triage: they are about
    the named company by construction."""
    now = now or datetime.now(timezone.utc)
    new = 0
    for item in items:
        symbols = sorted(set(item["symbols"]) | set(tag(f"{item['title']} {item['content'][:200]}", aliases)))
        filing = item["feed"] == "nse"
        insert = {
            "title": item["title"], "url": item["url"], "source": item["source"],
            "published_at": item["published_at"], "content": item["content"], "scope_hint": item["scope_hint"],
            "fetched_at": now, "attempts": 0,
            "status": TRIAGED if filing else NEW,
            "expire_at": now + (RELEVANT_TTL if filing else IRRELEVANT_TTL),
            **({"relevant": True, "scope": "COMPANY", "themes": [], "region": "IN", "triaged_at": now} if filing else {}),
        }
        result = await db[COLLECTION].update_one(
            {"_id": item_id(item["title"])},
            {"$setOnInsert": insert, "$addToSet": {"symbols": {"$each": symbols}, "feeds": item["feed"]}},
            upsert=True,
        )
        new += result.upserted_id is not None
    return new


# ---------------------------------------------------------------------- LLM


class _Triage(BaseModel):
    index: int
    scope: str = "MARKET"
    themes: list[str] = []
    region: str = "OTHER"


class _Triages(BaseModel):
    items: list[_Triage] = []


class _Impact(BaseModel):
    type: Literal["market", "sector", "symbol"]
    target: str
    direction: float
    impact: float
    horizon: str = "days"


class _Scored(BaseModel):
    index: int
    event: str = ""
    impacts: list[_Impact] = []


class _Scores(BaseModel):
    items: list[_Scored] = []


async def _fast(system: str, user: str) -> str:
    # Triage only sorts headlines into relevant or not: the cheap model.
    return await llm_service.get_completion(user, system_prompt=system, tier="fast")


async def _deep(system: str, user: str) -> str:
    # These impacts feed every trade's AI share, same as score_news.
    return await llm_service.get_completion(user, system_prompt=system, tier="deep")


async def _ask(prompt: str, complete, model, **values):
    """One prompt, retried once on invalid JSON; None if still invalid."""
    system, user = render(prompt, **values)
    for attempt in (1, 2):
        response = await complete(system, user)
        try:
            return model.model_validate_json(_extract_json(response))
        except (ValueError, ValidationError) as exc:
            logger.warning("%s: invalid response (attempt %d): %s", prompt, attempt, exc)
    return None


async def _failed(db, ids: list[str]) -> None:
    await db[COLLECTION].update_many({"_id": {"$in": ids}}, {"$inc": {"attempts": 1}})
    await db[COLLECTION].update_many({"_id": {"$in": ids}, "attempts": {"$gte": MAX_ATTEMPTS}},
                                     {"$set": {"status": FAILED}})


async def _triage_batch(db, docs: list[dict], now: datetime) -> None:
    listing = "\n".join(f"[{i}] [{d['scope_hint']}] {d['title']} ({d['source']})" for i, d in enumerate(docs))
    result = await _ask("triage_news", _fast, _Triages, items=listing)
    if result is None:
        await _failed(db, [d["_id"] for d in docs])
        return
    kept = {t.index: t for t in result.items}
    for i, doc in enumerate(docs):
        t = kept.get(i)
        if t is not None:
            await db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {
                "status": TRIAGED, "relevant": True, "scope": t.scope if t.scope in SCOPES else doc["scope_hint"],
                "themes": t.themes[:3], "region": t.region, "triaged_at": now, "expire_at": now + RELEVANT_TTL}})
        else:
            await db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {
                "status": IRRELEVANT, "relevant": False, "triaged_at": now}})


async def triage(db, now: Optional[datetime] = None, calls: int = TRIAGE_CALLS_PER_PASS) -> int:
    now = now or datetime.now(timezone.utc)
    docs = await db[COLLECTION].find({"status": NEW}).sort("fetched_at", 1).limit(
        TRIAGE_BATCH * calls).to_list(length=None)
    batches = [docs[i:i + TRIAGE_BATCH] for i in range(0, len(docs), TRIAGE_BATCH)]
    await asyncio.gather(*(_triage_batch(db, b, now) for b in batches))
    await _prune(db, now)
    return len(docs)


# Measured on 3 days of prod (2,443 scored): 0.7 caught 71 rewrites of one
# story and nothing else; 0.5 merged different companies' filings.
DUP_JACCARD, DUP_WINDOW = 0.7, timedelta(hours=24)
_STOP = {"the", "and", "for", "from", "with", "its", "after", "over", "amid", "says", "said", "india", "indian"}


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", _title_key(title)) if len(w) > 2 and w not in _STOP}


def _skip_reason(doc: dict, seen: list[set[str]]) -> Optional[str]:
    """Why a triaged item is not worth a deep call, or None. Hindi/regional
    copies repeat English stories; a company we follow no symbol of moves no
    score; a rewrite of a story already scored or queued adds nothing."""
    if sum(ord(c) > 0x2FF for c in doc["title"]) > 5:
        return "other_script"
    if doc.get("scope") == "COMPANY" and not doc.get("symbols"):
        return "unfollowed"
    words = _words(doc["title"])
    if words and any(len(words & s) / len(words | s) >= DUP_JACCARD for s in seen):
        return "duplicate"
    seen.append(words)
    return None


async def _prune(db, now: datetime) -> None:
    """Marks TRIAGED items that scoring would waste a deep call on IRRELEVANT."""
    # ponytail: O(pending x day's stories) title compare, ~1k x 1k per pass; index by word if news volume grows 10x.
    seen = [_words(d["title"]) async for d in db[COLLECTION].find(
        {"status": SCORED, "scored_at": {"$gte": now - DUP_WINDOW}}, {"title": 1})]
    async for doc in db[COLLECTION].find({"status": TRIAGED}).sort("published_at", 1):
        reason = _skip_reason(doc, seen)
        if reason:
            await db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {
                "status": IRRELEVANT, "relevant": False, "skip_reason": reason,
                "expire_at": now + IRRELEVANT_TTL}})


def valid_impacts(impacts: list[_Impact], symbols: set[str], sectors: set[str]) -> list[dict]:
    """Drops targets outside the known market/sectors/symbols and clamps the
    numbers: a hallucinated sector or a 12/10 impact never reaches a score."""
    out = []
    for i in impacts:
        if (i.type == "market" and i.target.upper() != MARKET_TARGET) or \
           (i.type == "sector" and i.target not in sectors) or \
           (i.type == "symbol" and i.target.upper() not in symbols):
            continue
        out.append({
            "type": i.type, "target": MARKET_TARGET if i.type == "market" else
            (i.target.upper() if i.type == "symbol" else i.target),
            "direction": max(-1.0, min(1.0, i.direction)), "impact": max(0.0, min(10.0, i.impact)),
            "horizon": i.horizon if i.horizon in ("intraday", "days", "weeks") else "days",
        })
    return out


async def _score_batch(db, docs, names, sector_of, sectors, now) -> None:
    lines = []
    for i, d in enumerate(docs):
        tagged = "; ".join(f"{s} ({names.get(s, s)}, {sector_of.get(s, 'sector unknown')})" for s in d.get("symbols", []))
        lines.append(f"[{i}] ({d.get('scope', d['scope_hint'])}) {d['title']}\n{(d.get('content') or '')[:400]}\n"
                     f"Tagged: {tagged or 'none'}")
    result = await _ask("score_market_news", _deep, _Scores, sectors=", ".join(sectors), items="\n\n".join(lines))
    if result is None:
        await _failed(db, [d["_id"] for d in docs])
        return
    scored = {s.index: s for s in result.items}
    for i, doc in enumerate(docs):
        s = scored.get(i)
        impacts = valid_impacts(s.impacts, set(names), set(sectors)) if s else []
        await db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {
            "status": SCORED, "impacts": impacts, "event": (s.event if s else "")[:120], "scored_at": now,
            "material": any(i["impact"] >= MATERIALITY_THRESHOLD for i in impacts)}})


async def score(db, names, sector_of, priority: set[str], calls: int, now: Optional[datetime] = None) -> int:
    """Scores up to `calls` batches, held/watched names first, then market,
    macro and global news, then the rest; newest first within each."""
    now = now or datetime.now(timezone.utc)
    await db[COLLECTION].update_many({"status": TRIAGED, "published_at": {"$lt": now - SCORE_MAX_AGE}},
                                     {"$set": {"status": STALE}})
    docs = await db[COLLECTION].find({"status": TRIAGED}).sort("published_at", -1).limit(500).to_list(length=None)
    docs.sort(key=lambda d: (0 if priority & set(d.get("symbols", [])) else
                             1 if d.get("scope") in ("MARKET", "MACRO", "GLOBAL") else 2))
    docs = docs[:SCORE_BATCH * calls]
    sectors = news_sources.sectors()
    batches = [docs[i:i + SCORE_BATCH] for i in range(0, len(docs), SCORE_BATCH)]
    await asyncio.gather(*(_score_batch(db, b, names, sector_of, sectors, now) for b in batches))
    return len(docs)


# ---------------------------------------------------------------- aggregate


def _blend(company: Optional[float], sector: Optional[float], market: Optional[float]) -> float:
    value = COMPANY_WEIGHT * (company or 0.0) + SECTOR_WEIGHT * (sector or 0.0) + MARKET_WEIGHT * (market or 0.0)
    return max(-1.0, min(1.0, value))


async def aggregate(db, redis, names: dict[str, str], sector_of: dict[str, str], now: Optional[datetime] = None) -> dict:
    """Recomputes every followed symbol's sentiment, every sector's, and
    the market's from the scored items in WINDOW, and writes them."""
    from backend.datalayer.outcomes import item_weight, load_weights

    now = now or datetime.now(timezone.utc)
    weights = await load_weights(redis)
    points = defaultdict(list)
    top = {}  # symbol -> (impact, event) of its biggest company item in VERDICT_WINDOW
    cursor = db[COLLECTION].find({"status": SCORED, "published_at": {"$gte": now - WINDOW}},
                                 {"impacts": 1, "published_at": 1, "event": 1, "title": 1, "scope": 1, "themes": 1})
    async for doc in cursor:
        published = doc["published_at"]
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        for i in doc.get("impacts", []):
            weight = item_weight(weights, doc.get("scope"), doc.get("themes"), i["direction"])
            points[(i["type"], i["target"])].append((published, i["direction"], i["impact"] * weight))
            if i["type"] == "symbol" and published >= now - VERDICT_WINDOW and i["impact"] > top.get(i["target"], (-1,))[0]:
                top[i["target"]] = (i["impact"], doc.get("event") or doc.get("title", ""))

    def mean(key):
        return weighted_sentiment(points.get(key, []), now)

    market = mean(("market", MARKET_TARGET))
    sectors = {s: mean(("sector", s)) for s in news_sources.sectors()}
    symbols = {s: _blend(mean(("symbol", s)), sectors.get(sector_of.get(s)), market) for s in names}

    async with redis.pipeline(transaction=False) as pipe:
        pipe.set("market:sentiment", json.dumps({"score": market, "n": len(points.get(("market", MARKET_TARGET), [])),
                                                 "at": now.timestamp()}), ex=SENTIMENT_TTL_SECONDS)
        for sector, value in sectors.items():
            pipe.set(f"sector_sentiment:{sector}", json.dumps({
                "score": value, "n": len(points.get(("sector", sector), [])), "at": now.timestamp()}),
                ex=SENTIMENT_TTL_SECONDS)
        for symbol, value in symbols.items():
            pipe.set(f"sentiment:{symbol}", value, ex=SENTIMENT_TTL_SECONDS)
        for symbol, (impact, reason) in top.items():
            if symbol not in symbols:
                continue
            value = symbols[symbol]
            pipe.set(f"analyst_verdict:{symbol}", json.dumps({
                "sentiment_score": value, "impact_score": int(round(impact)),
                "label": "bullish" if value > 0.15 else "bearish" if value < -0.15 else "neutral",
                "top_reason": reason[:200],
            }), ex=VERDICT_TTL_SECONDS)
        await pipe.execute()
    return {"market": market, "sectors": sectors, "symbols": symbols}


# -------------------------------------------------------------------- loops

_indexed = False
_aliases: tuple[frozenset, list] = (frozenset(), [])
_last_aggregate = 0.0
_last_llm_pass = 0.0


async def poll_loop(db, redis) -> None:
    global _indexed, _aliases
    if not _indexed:
        await ensure_indexes(db)
        _indexed = True
    names, _ = await followed(db)
    key = frozenset(names.items())
    if key != _aliases[0]:
        _aliases = (key, build_aliases(names))
    items = await news_sources.poll(await priority_symbols(db), names)
    new = await store(db, items, _aliases[1])
    if new:
        logger.info("ingest news: %d new of %d fetched", new, len(items))


async def _deep_budget(redis, wanted: int) -> int:
    """Reserves up to `wanted` deep calls from today's (IST) allowance,
    NEWS_LLM_CALLS_PER_DAY; past it the backlog waits for tomorrow (and goes
    STALE after SCORE_MAX_AGE) rather than eating the shared LLM quota."""
    from backend.engine.session import IST

    key = f"news:deep_calls:{datetime.now(timezone.utc).astimezone(IST).date().isoformat()}"
    used = int(await redis.get(key) or 0)
    granted = max(0, min(wanted, settings.NEWS_LLM_CALLS_PER_DAY - used))
    if granted:
        await redis.incrby(key, granted)
        await redis.expire(key, 2 * 86400)
    return granted


async def _score_due(db, priority: set[str], now: datetime) -> bool:
    pending = {"status": TRIAGED}
    return bool(
        await db[COLLECTION].count_documents(pending, limit=SCORE_MIN_ITEMS) >= SCORE_MIN_ITEMS
        or await db[COLLECTION].count_documents({**pending, "symbols": {"$in": list(priority)}}, limit=1)
        or await db[COLLECTION].count_documents({**pending, "triaged_at": {"$lte": now - SCORE_HOLD}}, limit=1))


async def process_loop(db, redis) -> None:
    global _last_aggregate, _last_llm_pass
    from backend.engine.autorun import near_session

    names, sector_of = await followed(db)
    triaged = scored = 0
    now = datetime.now(timezone.utc)
    active = near_session(now)
    if active or time.time() - _last_llm_pass >= OFF_PROCESS_SECONDS:
        _last_llm_pass = time.time()
        triaged = await triage(db, calls=TRIAGE_CALLS_PER_PASS if active else OFF_TRIAGE_CALLS)
        priority = await priority_symbols(db)
        # Off-hours the pass is already hourly, so it scores whatever waits.
        calls = await _deep_budget(redis, 1) if await (_score_due(db, priority, now) if active else
                                                       db[COLLECTION].count_documents({"status": TRIAGED}, limit=1)) else 0
        scored = await score(db, names, sector_of, priority, calls) if calls else 0
    if scored or time.time() - _last_aggregate >= AGGREGATE_EVERY_SECONDS:
        await aggregate(db, redis, names, sector_of)
        _last_aggregate = time.time()
    if triaged or scored:
        logger.info("ingest news: triaged %d, scored %d", triaged, scored)
