"""Builds a user's pre-open game plan: the datalayer's market read, the
strategy library and the stocks in play go into one `deep` call, and what
comes back is validated (backend/plan/validate.py) before it is stored.
Any failure -- budget spent, model error, unparseable reply -- stores the
fallback plan, which is today's behaviour."""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from backend.ai.sentiment import get_cached_sentiment
from backend.datalayer.catalysts import catalyst_map
from backend.datalayer.news_sources import nifty200_sectors
from backend.engine.session import IST
from backend.llm import llm_service
from backend.plan import store
from backend.plan.validate import fallback_plan, validate
from backend.prefs import PrefsStore
from backend.prompts import render

logger = logging.getLogger(__name__)

MAX_NEWS_NAMES = 30
BRIEF_CHARS = 1500
CARD_KEYS = ("style", "regimes", "needs", "best_when", "avoid_when")


def intraday_strategies() -> set[str]:
    from backend.learning.library import _strategies

    return {s.spec.name for s in _strategies() if s.spec.mode == "INTRADAY"}


def _bare(symbol: str) -> str:
    return symbol.upper().removesuffix(".NS")


async def _llm(system: str, prompt: str) -> str:
    return await llm_service.get_completion(prompt, system_prompt=system, tier="deep")


async def _json(redis, key: str) -> Optional[dict]:
    raw = await redis.get(key)
    return json.loads(raw) if raw else None


async def _held_and_watched(db, user_id: str) -> set[str]:
    held = await db["paper_positions"].distinct("symbol", {"user_id": user_id, "quantity": {"$ne": 0}})
    watch = await db["watchlist"].find_one({"user_id": user_id}) or {}
    return {_bare(s) for s in [*held, *(watch.get("symbols") or [])] if s}


async def _headlines(db, symbols: set[str], since: datetime) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    docs = await db["news_items"].find(
        {"status": "SCORED", "published_at": {"$gte": since}, "impacts.target": {"$in": sorted(symbols)}},
        {"title": 1, "impacts": 1},
    ).sort("published_at", -1).to_list(length=300)
    for d in docs:
        for i in d.get("impacts") or []:
            if i.get("type") == "symbol" and i.get("target") in symbols and len(out.setdefault(i["target"], [])) < 2:
                out[i["target"]].append(f"{d['title']} ({i['direction']:+.1f}/{i['impact']:.0f})")
    return out


async def _context(db, redis, user_id: str, prefs: dict, universe: set[str], now: datetime) -> dict:
    from backend.datalayer.market import upcoming
    from backend.learning.library import catalog

    today = now.astimezone(IST).date()
    sectors = nifty200_sectors()
    catalysts = (await catalyst_map(db, today, today)).get(today.isoformat(), {})
    news_names = sorted((s for s in catalysts if s in sectors and s not in universe),
                        key=lambda s: -abs(catalysts[s]))[:MAX_NEWS_NAMES]
    candidates = sorted(universe | await _held_and_watched(db, user_id)) + news_names
    heads = await _headlines(db, set(candidates), now - timedelta(hours=18))
    rows = [{"symbol": s, "in_universe": s in universe, "sector": sectors.get(s),
             "sentiment": await get_cached_sentiment(s, redis), "catalyst": catalysts.get(s),
             "news": heads.get(s, [])} for s in candidates]

    cards = [{"name": c["name"], **{k: c["card"][k] for k in CARD_KEYS},
              "backtest_passed": (c["backtest"] or {}).get("passed"), "paper_passed": c["paper"]["passed"],
              "learned": c["learned"], "record": c["stats"]["all"]}
             for c in await catalog(db, user_id, [], mode="INTRADAY")]
    regime = await _json(redis, "market:regime") or {}
    brief = await _json(redis, "market:brief") or {}
    flows = await _json(redis, "market:flows") or {}
    events = await upcoming(db, hours=8, now=now)
    return {
        "now": now.astimezone(IST).strftime("%a %d %b %Y %H:%M IST"),
        "regime": f"{regime.get('label', 'unknown')} ({regime.get('score', 0):+.2f}): "
                  + ("; ".join(regime.get("drivers") or []) or "no strong drivers"),
        "brief": (brief.get("text") or "none yet")[:BRIEF_CHARS],
        "flows": json.dumps(flows) if flows else "unavailable",
        "calendar": "\n".join(f"- {e['at'].astimezone(IST).strftime('%H:%M')} {e.get('country', '')} {e.get('title', '')}"
                              for e in events) or "- none",
        "strategies": json.dumps(cards, default=str),
        "candidates": json.dumps(rows, default=str),
        "caps": json.dumps({k: prefs.get(k) for k in ("account_size", "per_trade_cap", "max_exposure",
                                                       "daily_loss_limit")}),
    }


async def build_plan(db, redis, user_id: str, now: datetime, complete=None) -> dict:
    complete = complete or _llm
    today = now.astimezone(IST).date()
    prefs = await PrefsStore(db).get(user_id)
    universe = {_bare(s) for s in prefs["universe"] or []}
    strategies = intraday_strategies()

    async def fallback(reason: str) -> dict:
        logger.info("game plan for %s: fallback (%s)", user_id, reason)
        return await store.save(db, redis, user_id, today, fallback_plan(strategies, universe, reason), now)

    system, prompt = render("game_plan", **await _context(db, redis, user_id, prefs, universe, now))
    reason = "no reply"
    for _ in range(2):  # one retry; each attempt is a call against the daily budget
        if not await store.reserve_call(redis, today):
            return await fallback("daily AI plan budget used up")
        reply = (await complete(system, prompt) or "").strip()
        if not reply or reply == "LLM_DISABLED" or reply.startswith("Error generating response"):
            reason = f"AI unavailable ({reply[:80] or 'empty'})"
            continue
        try:
            plan = validate(reply, trigger="pre_open", strategies=strategies, universe=universe,
                            nifty200=set(nifty200_sectors()))
        except ValueError as exc:
            reason = f"unreadable plan ({exc})"
            continue
        return await store.save(db, redis, user_id, today, plan, now)
    return await fallback(reason)
