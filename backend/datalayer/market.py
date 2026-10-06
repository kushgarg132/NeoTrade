"""The market backdrop: economic calendar, FII/DII flows, a rule-based
risk regime, and one short AI-written market brief.

    calendar  (6h)   ForexFactory's weekly JSON -> Mongo `econ_calendar`
    flows     (30m)  NSE FII/DII cash flows -> Redis `market:flows`, Mongo `macro_series`
    regime    (60s)  rules over news + macro numbers -> Redis `market:regime` (no LLM)
    brief     (60s)  at most one LLM call when due -> Redis `market:brief`

The brief is the only LLM call here, and it is rationed: every
BRIEF_SESSION_SECONDS in session (and the 45 min before the open),
BRIEF_OFF_SECONDS outside, or sooner in session (but not within
BRIEF_MIN_GAP_SECONDS) when a material market/macro/global item has been
scored since the last brief.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from backend.datalayer.news import COLLECTION, SCORED
from backend.datalayer.news_sources import UA
from backend.datalayer.prices import MACRO, MACRO_KEY
from backend.engine.autorun import near_session
from backend.engine.session import IST
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FLOWS_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
# Countries whose releases move Indian markets ("All" is OPEC and the like).
CALENDAR_COUNTRIES = {"USD", "CNY", "EUR", "JPY", "GBP", "All"}

REGIME_KEY, BRIEF_KEY, FLOWS_KEY = "market:regime", "market:brief", "market:flows"
REGIME_TTL_SECONDS = 3600
RISK_OFF, RISK_ON = -0.5, 0.3

BRIEF_SESSION_SECONDS = 60 * 60
BRIEF_OFF_SECONDS = 6 * 3600
BRIEF_MIN_GAP_SECONDS = 15 * 60
BRIEF_ITEMS = 25


def _fetch_json(url: str, referer: Optional[str] = None):
    headers = {**UA, **({"Referer": referer} if referer else {})}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


# ----------------------------------------------------------------- calendar


def parse_calendar(rows: list[dict]) -> list[dict]:
    events = []
    for r in rows:
        if r.get("impact") not in ("High", "Medium") or r.get("country") not in CALENDAR_COUNTRIES:
            continue
        try:
            at = datetime.fromisoformat(r["date"]).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        events.append({"_id": f"{r['date']}:{r['country']}:{r['title']}", "at": at, "country": r["country"],
                       "title": r["title"], "impact": r["impact"], "forecast": r.get("forecast") or None,
                       "previous": r.get("previous") or None})
    return events


async def calendar(db, redis) -> None:
    rows = await asyncio.to_thread(_fetch_json, CALENDAR_URL)
    for event in parse_calendar(rows):
        await db["econ_calendar"].replace_one({"_id": event["_id"]}, event, upsert=True)


async def upcoming(db, hours: float = 48, now: Optional[datetime] = None, high_only: bool = True) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    query = {"at": {"$gte": now, "$lte": now + timedelta(hours=hours)}}
    if high_only:
        query["impact"] = "High"
    return await db["econ_calendar"].find(query, {"_id": 0}).sort("at", 1).to_list(length=50)


# -------------------------------------------------------------------- flows


async def flows(db, redis) -> None:
    rows = await asyncio.to_thread(_fetch_json, FLOWS_URL, "https://www.nseindia.com/")
    out = {}
    for r in rows:
        key = "FII" if r.get("category", "").startswith("FII") else "DII" if r.get("category") == "DII" else None
        if key:
            out[key] = float(r["netValue"])
            out["date"] = r.get("date")
    if not out.get("date"):
        return
    now = datetime.now(timezone.utc)
    await redis.set(FLOWS_KEY, json.dumps({**out, "at": now.timestamp()}), ex=4 * 86400)
    for key in ("FII", "DII"):
        if key in out:
            await db["macro_series"].update_one(
                {"_id": f"{key}_NET:{out['date']}"},
                {"$set": {"ticker": f"{key}_NET", "date": out["date"], "value": out[key], "at": now}}, upsert=True)


# ------------------------------------------------------------------- regime


async def _json(redis, key: str) -> Optional[dict]:
    raw = await redis.get(key)
    return json.loads(raw) if raw else None


def compute_regime(news_score: Optional[float], macro: dict[str, dict], flows: Optional[dict],
                   event_soon: Optional[dict]) -> dict:
    """Plain rules, no LLM: half the score is the market-wide news
    sentiment, the rest is what the numbers are doing right now."""
    score, drivers = 0.5 * (news_score or 0.0), []
    if news_score is not None and abs(news_score) >= 0.2:
        drivers.append(f"market news sentiment {news_score:+.2f}")

    def pct(ticker):
        return (macro.get(ticker) or {}).get("percent")

    vix = (macro.get("^INDIAVIX") or {}).get("value")
    if vix is not None and vix >= 20:
        score -= 0.5 if vix >= 25 else 0.3
        drivers.append(f"India VIX high at {vix:.1f}")
    if (pct("^INDIAVIX") or 0) >= 10:
        score -= 0.2
        drivers.append(f"India VIX up {pct('^INDIAVIX'):+.1f}%")
    crude = pct("BZ=F")
    if crude is not None and abs(crude) >= 3:
        score += -0.2 if crude > 0 else 0.1
        drivers.append(f"Brent {crude:+.1f}%")
    rupee = pct("INR=X")
    if rupee is not None and abs(rupee) >= 0.5:
        score += -0.15 if rupee > 0 else 0.05
        drivers.append(f"rupee {'weaker' if rupee > 0 else 'stronger'} ({rupee:+.2f}% USD/INR)")
    futures = pct("ES=F")
    if futures is not None and abs(futures) >= 1:
        score += -0.2 if futures < 0 else 0.1
        drivers.append(f"S&P futures {futures:+.1f}%")
    fii = (flows or {}).get("FII")
    if fii is not None and abs(fii) >= 3000:
        score += -0.1 if fii < 0 else 0.1
        drivers.append(f"FII net {fii:+,.0f} cr")
    if event_soon:
        drivers.append(f"high-impact event soon: {event_soon['country']} {event_soon['title']}")

    score = max(-1.0, min(1.0, score))
    label = "risk_off" if score <= RISK_OFF else "risk_on" if score >= RISK_ON else "neutral"
    return {"score": round(score, 3), "label": label, "drivers": drivers,
            "event_soon": event_soon and {"title": event_soon["title"], "country": event_soon["country"],
                                          "at": event_soon["at"].isoformat()}}


async def regime(db, redis) -> None:
    now = datetime.now(timezone.utc)
    raws = await redis.mget([MACRO_KEY.format(t) for t in MACRO.values()])
    macro = {t: json.loads(r) for t, r in zip(MACRO.values(), raws) if r}
    news = await _json(redis, "market:sentiment")
    soon = await upcoming(db, hours=0.5, now=now)
    result = compute_regime((news or {}).get("score"), macro, await _json(redis, FLOWS_KEY), soon[0] if soon else None)
    await redis.set(REGIME_KEY, json.dumps({**result, "at": now.timestamp()}), ex=REGIME_TTL_SECONDS)


# -------------------------------------------------------------------- brief


async def top_items(db, hours: float, scopes=("MARKET", "MACRO", "GLOBAL", "SECTOR"), limit: int = BRIEF_ITEMS,
                    now: Optional[datetime] = None) -> list[dict]:
    """The highest-impact scored items of the last `hours`."""
    now = now or datetime.now(timezone.utc)
    docs = await db[COLLECTION].find(
        {"status": SCORED, "scope": {"$in": list(scopes)}, "published_at": {"$gte": now - timedelta(hours=hours)},
         "impacts.0": {"$exists": True}},
        {"title": 1, "source": 1, "published_at": 1, "scope": 1, "impacts": 1, "event": 1, "url": 1},
    ).to_list(length=1000)
    docs.sort(key=lambda d: max(i["impact"] for i in d["impacts"]), reverse=True)
    return docs[:limit]


def _brief_due(last: Optional[dict], material_since: bool, now: datetime, regime_changed: bool = True) -> bool:
    if last is None:
        return True
    age = now.timestamp() - last["at"]
    if age < BRIEF_MIN_GAP_SECONDS:
        return False
    if not near_session(now):
        # Off-hours big news waits for the pre-open brief; nothing trades on it before then.
        return age >= BRIEF_OFF_SECONDS
    if material_since or not near_session(datetime.fromtimestamp(last["at"], timezone.utc)):
        return True  # big news, or the first brief of this session's run-up
    # The hourly slot is skipped when nothing moved: same regime, no material item.
    return age >= BRIEF_SESSION_SECONDS and regime_changed


async def _write_brief(system: str, prompt: str) -> str:
    # One short summary for every user and every AI answer: the mid tier.
    return await llm_service.get_completion(prompt, system_prompt=system, tier="standard", feature="news")


async def brief(db, redis, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    last = await _json(redis, BRIEF_KEY)
    material_since = bool(await db[COLLECTION].count_documents({
        "material": True, "scope": {"$in": ["MARKET", "MACRO", "GLOBAL"]},
        "scored_at": {"$gt": datetime.fromtimestamp(last["at"], timezone.utc) if last else now - timedelta(days=1)},
    }, limit=1))
    regime_now = await _json(redis, REGIME_KEY) or {}
    if not _brief_due(last, material_since, now, regime_changed=(last or {}).get("regime") != regime_now.get("label")):
        return False

    items = await top_items(db, hours=24, now=now)
    if not items:
        return False
    raws = await redis.mget([MACRO_KEY.format(t) for t in MACRO.values()])
    board = [json.loads(r) for r in raws if r]
    if last and last.get("items") == [str(d["_id"]) for d in items] and last.get("regime") == regime_now.get("label"):
        return False  # same top stories, same regime: the brief would say the same thing again
    flows_now = await _json(redis, FLOWS_KEY) or {}
    events = await upcoming(db, hours=48, now=now)

    def impacts(d):
        return ", ".join(f"{i['target']} {i['direction']:+.1f}/{i['impact']:.0f}" for i in d["impacts"][:4])

    system, prompt = render(
        "market_brief",
        now=now.astimezone(IST).strftime("%a %d %b %Y %H:%M IST"),
        news="\n".join(f"- [{d['scope']}] {d['title']} ({d.get('source', '')}) -> {impacts(d)}" for d in items),
        board="\n".join(f"- {r['name']}: {r['value']:,.2f} ({r['percent']:+.2f}%)" for r in board) or "- unavailable",
        flows=(f"FII net {flows_now['FII']:+,.0f} cr, DII net {flows_now['DII']:+,.0f} cr on {flows_now['date']}"
               if "FII" in flows_now and "DII" in flows_now else "unavailable"),
        regime=f"{regime_now.get('label', 'unknown')} ({regime_now.get('score', 0):+.2f}): "
               + ("; ".join(regime_now.get("drivers", [])) or "no strong drivers"),
        calendar="\n".join(f"- {e['at'].astimezone(IST).strftime('%a %H:%M IST')} {e['country']} {e['title']}"
                           for e in events) or "- nothing high-impact in the next 48 hours",
    )
    text = (await _write_brief(system, prompt) or "").strip()
    if not text or text == "LLM_DISABLED" or text.startswith("Error generating response"):
        return False
    doc = {"text": text, "at": now.timestamp(), "regime": regime_now.get("label"),
           "items": [str(d["_id"]) for d in items]}
    await redis.set(BRIEF_KEY, json.dumps(doc))
    return True


async def backdrop(redis) -> dict:
    """What every AI answer and report gets: the brief and the regime.
    Empty when the ingest worker has not produced them."""
    if redis is None:
        return {}
    try:
        return {"brief": (await _json(redis, BRIEF_KEY) or {}).get("text"), "regime": await _json(redis, REGIME_KEY)}
    except Exception as exc:
        logger.warning("market backdrop unavailable: %s", exc)
        return {}
