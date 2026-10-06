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

`scan` (its own loop, claimed with `scanned_at`) re-runs the long-term scan
(backend/suggestions/scan.py, the same strategies and composite scoring)
for the names a material item moves, directly or via their sector, within
each scan-enabled user's universe: at most once per user and symbol a day
and MAX_SCAN_SYMBOLS per user a pass. Proposals land PENDING with
source="news", get a thesis and a Telegram message like the 16:00 scan's.
Market-wide items trigger no scan: they move every name, not some. With
the autopilot and `autopilot_news` on, the new stock proposals go to the
autopilot at once, source="news", through its fence (at most 3 a day; none
while risk-off).

`shadow_exits` records, in `autopilot_shadow`, the SELL the autopilot would
place when a material negative item (impact >= EXIT_IMPACT, direction <=
EXIT_DIRECTION, on the symbol or its sector) hits one of its longs. No order
is sent: real news exits wait for a review of this log
(docs/superpowers/specs/2026-10-05-autopilot-news-design.md).
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
SCAN_KEY = "news:scanned:{}:{}"
SCAN_TTL_SECONDS = 24 * 3600
MAX_SCAN_SYMBOLS = 20
EXIT_IMPACT, EXIT_DIRECTION = 8, -0.5
SHADOW_KEY = "news:shadow:{}:{}"


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


def scan_targets(item: dict, sector_of: dict[str, str], universe: set[str]) -> list[str]:
    """Universe names `item` materially moves: direct hits first, then the
    names in a sector it moves."""
    material = [i for i in item.get("impacts", []) if i["impact"] >= MATERIALITY_THRESHOLD]
    direct = [i["target"] for i in material if i["type"] == "symbol" and i["target"] in universe]
    sectors = {i["target"] for i in material if i["type"] == "sector"}
    return direct + sorted(s for s in universe if sector_of.get(s) in sectors and s not in direct)


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


async def _claim(db, field: str, now: datetime) -> list[dict]:
    """Newly scored material items not yet handled by `field`'s reaction,
    marked handled before anything is done with them."""
    items = await db[COLLECTION].find({
        "status": SCORED, "material": True, field: {"$exists": False},
        "scored_at": {"$gte": now - SCORED_WITHIN}, "published_at": {"$gte": now - MAX_NEWS_AGE},
    }).to_list(length=200)
    if items:
        await db[COLLECTION].update_many({"_id": {"$in": [i["_id"] for i in items]}}, {"$set": {field: now}})
    return items


async def react(db, redis, now: Optional[datetime] = None) -> int:
    """Alerts every newly scored material item; returns how many alerts went out."""
    from backend.datalayer.news import followed

    now = now or datetime.now(timezone.utc)
    items = await _claim(db, "reacted_at", now)
    if not items:
        return 0

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


async def _scan_user(db, redis, prefs: dict, symbols: list[str], now: datetime) -> list[dict]:
    from backend.suggestions.notify import notify, proposals_text
    from backend.suggestions.scan import scan_universe
    from backend.suggestions.thesis import attach_theses

    created = await scan_universe(db, user_id=prefs["user_id"], universe=symbols, account_size=prefs["account_size"],
                                  max_exposure=prefs["max_exposure"], source="news", redis=redis, now=now)
    if not created:
        return created
    await attach_theses(db, prefs["user_id"], created)
    left = created
    if prefs.get("autopilot_enabled") and prefs.get("autopilot_news"):
        from backend.engine.autorun import _autopilot_proposals
        from backend.suggestions.store import SuggestionStore

        left = await _autopilot_proposals(db, redis, SuggestionStore(db), prefs["user_id"], created, now,
                                          source="news", heading="news trade")
    if left:
        await notify(db, prefs["user_id"], proposals_text(left, f"{len(left)} new long-term proposal(s) after news:"))
    return created


async def scan(db, redis, now: Optional[datetime] = None) -> int:
    """Re-scans the names newly scored material news moves; returns how many
    proposals it made."""
    from backend.datalayer.news import followed
    from backend.prefs import PrefsStore

    now = now or datetime.now(timezone.utc)
    items = await _claim(db, "scanned_at", now)
    if not items:
        return 0
    _, sector_of = await followed(db)
    made = 0
    for prefs in await PrefsStore(db).scan_enabled_users():
        universe = {_bare(s) for s in prefs["universe"]}
        wanted = list(dict.fromkeys(s for item in items for s in scan_targets(item, sector_of, universe)))
        symbols = []
        for symbol in wanted:
            if len(symbols) == MAX_SCAN_SYMBOLS:
                break
            if await redis.set(SCAN_KEY.format(prefs["user_id"], symbol), "1", ex=SCAN_TTL_SECONDS, nx=True):
                symbols.append(symbol)
        if not symbols:
            continue
        try:
            made += len(await _scan_user(db, redis, prefs, symbols, now))
        except Exception as exc:
            logger.exception("news scan failed for %s: %s", prefs["user_id"], exc)
    if made:
        logger.info("news scan: %d proposal(s) from %d item(s)", made, len(items))
    return made


def exit_hit(item: dict, symbol: str, sector_of: dict[str, str]) -> Optional[dict]:
    """The impact on `item` bad enough to sell `symbol` on, if any."""
    for i in item.get("impacts", []):
        if i["impact"] >= EXIT_IMPACT and i["direction"] <= EXIT_DIRECTION and (
                (i["type"] == "symbol" and i["target"] == symbol) or
                (i["type"] == "sector" and sector_of.get(symbol) == i["target"])):
            return i
    return None


async def shadow_exits(db, redis, now: Optional[datetime] = None) -> int:
    """Logs the news exits the autopilot would make; places nothing."""
    from backend.autopilot.service import _product, open_trades
    from backend.datalayer.news import followed

    now = now or datetime.now(timezone.utc)
    items = await _claim(db, "exit_checked_at", now)
    if not items:
        return 0
    users = [d["user_id"] async for d in db["user_prefs"].find(
        {"autopilot_enabled": True, "autopilot_news": True}, {"user_id": 1})]
    if not users:
        return 0
    _, sector_of = await followed(db)
    logged = 0
    for user_id in users:
        for trade in await open_trades(db, user_id):
            if trade.get("side") != "BUY":
                continue
            for item in items:
                hit = exit_hit(item, trade["symbol"], sector_of)
                if hit and await redis.set(SHADOW_KEY.format(user_id, trade["symbol"]), "1",
                                           ex=SCAN_TTL_SECONDS, nx=True):
                    await db["autopilot_shadow"].insert_one({
                        "user_id": user_id, "at": now, "side": "SELL", "symbol": trade["symbol"],
                        "quantity": trade["quantity"], "product": _product(trade), "venue": trade.get("venue"),
                        "news_id": item["_id"], "title": item.get("event") or item["title"], "impact": hit})
                    logged += 1
                    break
    if logged:
        logger.info("news shadow exits: %d would-sell(s)", logged)
    return logged
