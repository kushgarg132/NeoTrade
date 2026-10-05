"""Reactions to scored news: tell the users a material item matters to.

Runs in the ingest worker every minute over items scored since the last
pass (news.py marks them SCORED + `material`). Each item is claimed once
with `reacted_at`, so a restart or a second pass never alerts it twice.

Who hears about it, by the user's `news_alerts` preference:
    held          (default) items moving a name they hold, directly or via its sector
    held+watched  the same over held and watched names
    all           every material item
    off           nothing
A market-wide shock (an impact >= SHOCK_IMPACT on the Indian market) also
goes to everyone with an open position, unless they chose `off`.

One alert per user and target (symbol, or INDIA for a shock) an hour. An
alert is a Telegram message (a no-op for an unlinked user) plus a `news`
event on the user's socket, which the app shows as a toast.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.datalayer.news import COLLECTION, MARKET_TARGET, SCORED
from backend.datalayer.prices import _bare
from backend.strategies.longterm.analyst_verdict import MATERIALITY_THRESHOLD

logger = logging.getLogger(__name__)

SHOCK_IMPACT = 7
SCORED_WITHIN = timedelta(minutes=30)  # a pass that missed this window has nothing urgent left to say
MAX_NEWS_AGE = timedelta(hours=6)  # scored late, it is no longer news
ALERT_KEY = "news:alerted:{}:{}"
ALERT_TTL_SECONDS = 3600
PREFS = ("held", "held+watched", "all", "off")


def hits_for(item: dict, sector_of: dict[str, str], pref: str, held: set[str], watched: set[str]) -> list[dict]:
    """The impacts on `item` this user should hear about, as alert targets."""
    if pref == "off":
        return []
    follow = held | watched if pref == "held+watched" else held
    hits = {}
    for i in item.get("impacts", []):
        if i["type"] == "market":
            if i["impact"] >= SHOCK_IMPACT and (held or pref == "all"):
                hits[MARKET_TARGET] = i
        elif i["impact"] < MATERIALITY_THRESHOLD:
            continue
        elif pref == "all":
            hits[i["target"]] = i
        elif i["type"] == "symbol" and i["target"] in follow:
            hits[i["target"]] = i
        elif i["type"] == "sector":
            for symbol in follow:
                if sector_of.get(symbol) == i["target"]:
                    hits.setdefault(symbol, i)  # a direct hit on the symbol wins
    return [{"target": t, "direction": i["direction"], "impact": i["impact"]} for t, i in hits.items()]


def alert_text(item: dict, hits: list[dict]) -> str:
    moves = ", ".join(
        f"{'Market' if h['target'] == MARKET_TARGET else h['target']} {'↑' if h['direction'] > 0 else '↓'} {h['impact']:g}/10"
        for h in hits
    )
    return "\n".join(filter(None, [f"📰 {item.get('event') or item['title']}", moves, item.get("url")]))


async def _audience(db) -> dict[str, tuple[str, set[str], set[str]]]:
    """user_id -> (news_alerts pref, held symbols, watched symbols), for every
    user who holds or watches something or asked for all news."""
    held, watched = defaultdict(set), defaultdict(set)
    async for row in db["paper_positions"].find({"quantity": {"$ne": 0}}, {"user_id": 1, "symbol": 1}):
        held[row["user_id"]].add(_bare(row["symbol"]))
    async for row in db["watchlist"].find({}, {"user_id": 1, "symbols": 1}):
        watched[row["user_id"]].update(_bare(s) for s in row.get("symbols") or [])
    prefs = {d["user_id"]: d.get("news_alerts", "held")
             async for d in db["user_prefs"].find({}, {"user_id": 1, "news_alerts": 1})}
    users = set(held) | set(watched) | {u for u, p in prefs.items() if p == "all"}
    return {u: (prefs.get(u, "held"), held[u], watched[u]) for u in users}


async def _deliver(db, redis, user_id: str, item: dict, hits: list[dict]) -> None:
    from backend.suggestions.notify import notify
    from backend.ws.hub import hub

    hub.attach_redis(redis)  # this process has no API startup to do it
    await hub.publish(user_id, "news", "alert", {
        "id": item["_id"], "title": item["title"], "event": item.get("event"), "url": item.get("url"),
        "source": item.get("source"), "published_at": item.get("published_at"), "hits": hits})
    try:
        await notify(db, user_id, alert_text(item, hits))
    except Exception as exc:
        logger.warning("news alert telegram for %s failed: %s", user_id, exc)


async def react(db, redis, now: Optional[datetime] = None) -> int:
    """Alerts every newly scored material item; returns how many alerts went out."""
    from backend.datalayer.news import followed

    now = now or datetime.now(timezone.utc)
    items = await db[COLLECTION].find({
        "status": SCORED, "material": True, "reacted_at": {"$exists": False},
        "scored_at": {"$gte": now - SCORED_WITHIN}, "published_at": {"$gte": now - MAX_NEWS_AGE},
    }).to_list(length=200)
    if not items:
        return 0
    await db[COLLECTION].update_many({"_id": {"$in": [i["_id"] for i in items]}}, {"$set": {"reacted_at": now}})

    _, sector_of = await followed(db)
    audience = await _audience(db)
    sent = 0
    for item in items:
        for user_id, (pref, held, watched) in audience.items():
            hits = [h for h in hits_for(item, sector_of, pref, held, watched)
                    if await redis.set(ALERT_KEY.format(user_id, h["target"]), "1", ex=ALERT_TTL_SECONDS, nx=True)]
            if hits:
                await _deliver(db, redis, user_id, item, hits)
                sent += 1
    if sent:
        logger.info("news reactor: %d alert(s) from %d item(s)", sent, len(items))
    return sent
