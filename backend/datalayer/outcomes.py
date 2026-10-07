"""What news actually did to prices, and how much each kind of news should count.

    record   each newly scored material item: a snapshot, per impact target,
             of its price now (a symbol's quote, a sector's members' quotes,
             or Nifty for the market) and Nifty's -> Mongo `news_outcomes`
    measure  at +1h (only for a snapshot taken in session), +1d and +5d:
             the target's return, Nifty's, and `move_{h}` = the target's
             return over Nifty's (the market's own return for a market target)
    weights  weekly: hit rate of each `scope|theme|direction` -- did the 1d
             move go the way the item said -- into `news_theme_weights` and
             Redis `news:theme_weights`, 1 + 2 * (hit rate - 0.5) clamped to
             0.5..1.5, only past MIN_SAMPLES outcomes

news.aggregate multiplies each impact by its item's weight, so themes that
moved prices count more in `sentiment:` and noise counts less. Prices come
from the quote and macro caches the ingest worker already fills: no fetches.
The snapshot is taken when the item is scored, minutes after it is published,
so a fast reaction may already be in the base price; the +1h horizon is the
noisiest for it.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.datalayer.prices import MACRO_KEY
from backend.marks import QUOTE_KEY

logger = logging.getLogger(__name__)

COLLECTION = "news_outcomes"
HORIZONS = {"1h": timedelta(hours=1), "1d": timedelta(days=1), "5d": timedelta(days=5)}
GRACE = timedelta(hours=12)  # a horizon missed by more than this (worker down) stays unmeasured
BENCH = "^NSEI"
MIN_SAMPLES = 20
WEIGHT_MIN, WEIGHT_MAX = 0.5, 1.5
WEIGHTS_KEY = "news:theme_weights"
WEIGHTS_DUE_KEY = "news:theme_weights:due"
WEIGHTS_EVERY_SECONDS = 7 * 86400
WEIGHTS_LOOKBACK = timedelta(days=180)


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def weight_key(scope: str, theme: str, direction: float) -> str:
    return f"{scope}|{theme}|{_sign(direction)}"


def item_weight(weights: dict[str, float], scope: Optional[str], themes: list[str], direction: float) -> float:
    """The mean weight of the item's themes for this direction; 1 when none is known."""
    known = [weights[k] for k in (weight_key(scope or "", t, direction) for t in themes or []) if k in weights]
    return sum(known) / len(known) if known else 1.0


def compute_weights(rows: list[dict]) -> dict[str, dict]:
    """rows: outcomes with scope, themes, direction and move_1d."""
    tally = defaultdict(lambda: [0, 0])  # key -> [hits, n]
    for row in rows:
        if row.get("move_1d") is None or not _sign(row["direction"]):
            continue
        hit = _sign(row["move_1d"]) == _sign(row["direction"])
        for theme in row.get("themes") or []:
            t = tally[weight_key(row.get("scope") or "", theme, row["direction"])]
            t[0] += hit
            t[1] += 1
    return {
        key: {"weight": max(WEIGHT_MIN, min(WEIGHT_MAX, 1 + 2 * (hits / n - 0.5))), "hit_rate": hits / n, "n": n}
        for key, (hits, n) in tally.items() if n >= MIN_SAMPLES
    }


def proven(weights: dict[str, float], scope: Optional[str], themes: list[str], direction: float) -> bool:
    """News the autopilot may trade on (ROADMAP 17.3.4): at least one of its
    themes measured for this direction (weights hold only themes past
    MIN_SAMPLES) and their mean weight above 1, i.e. a hit rate over 50%.
    Unmeasured news stays with the user as a proposal."""
    known = [weights[k] for k in (weight_key(scope or "", t, direction) for t in themes or []) if k in weights]
    return bool(known) and sum(known) / len(known) > 1


def basket_return(base: dict[str, float], now: dict[str, float]) -> Optional[float]:
    returns = [now[s] / p - 1 for s, p in base.items() if p and now.get(s)]
    return sum(returns) / len(returns) if returns else None


async def _prices(redis, symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    raws = await redis.mget([QUOTE_KEY.format(s) for s in symbols])
    return {s: json.loads(r)["ltp"] for s, r in zip(symbols, raws) if r}


async def _bench(redis) -> Optional[float]:
    raw = await redis.get(MACRO_KEY.format(BENCH))
    return json.loads(raw)["value"] if raw else None


def _members(kind: str, target: str, sector_of: dict[str, str]) -> list[str]:
    if kind == "symbol":
        return [target]
    if kind == "sector":
        return [s for s, sector in sector_of.items() if sector == target]
    return []  # the market is the benchmark itself


async def record(db, redis, now: Optional[datetime] = None) -> int:
    from backend.datalayer.news import followed
    from backend.datalayer.reactor import _claim
    from backend.engine.autorun import in_session

    now = now or datetime.now(timezone.utc)
    bench = await _bench(redis)
    if bench is None:
        return 0  # nothing to measure against: leave the items for the next pass
    items = await _claim(db, "outcome_at", now)
    if not items:
        return 0
    _, sector_of = await followed(db)
    stored = 0
    for item in items:
        for i in item.get("impacts", []):
            base = await _prices(redis, _members(i["type"], i["target"], sector_of))
            if i["type"] != "market" and not base:
                continue
            await db[COLLECTION].update_one({"_id": f"{item['_id']}:{i['type']}:{i['target']}"}, {"$setOnInsert": {
                "item_id": item["_id"], "type": i["type"], "target": i["target"], "scope": item.get("scope"),
                "themes": item.get("themes") or [], "direction": i["direction"], "impact": i["impact"],
                "published_at": item["published_at"], "base_at": now, "in_session": in_session(now),
                "base": base, "bench": bench}}, upsert=True)
            stored += 1
    return stored


async def measure(db, redis, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    bench = await _bench(redis)
    if bench is None:
        return 0
    done = 0
    for h, delta in HORIZONS.items():
        query = {f"move_{h}": {"$exists": False}, "base_at": {"$lte": now - delta, "$gte": now - delta - GRACE}}
        if h == "1h":
            query["in_session"] = True
        async for doc in db[COLLECTION].find(query):
            bench_ret = bench / doc["bench"] - 1
            if doc["type"] == "market":
                ret, move = bench_ret, bench_ret
            else:
                ret = basket_return(doc["base"], await _prices(redis, list(doc["base"])))
                move = None if ret is None else ret - bench_ret
            await db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {
                f"ret_{h}": ret, f"bench_{h}": bench_ret, f"move_{h}": move}})
            done += 1
    return done


async def weights(db, redis, now: Optional[datetime] = None) -> Optional[dict]:
    """Recomputes the theme weights at most once a week."""
    now = now or datetime.now(timezone.utc)
    if not await redis.set(WEIGHTS_DUE_KEY, "1", ex=WEIGHTS_EVERY_SECONDS, nx=True):
        return None
    rows = await db[COLLECTION].find(
        {"move_1d": {"$ne": None}, "base_at": {"$gte": now - WEIGHTS_LOOKBACK}},
        {"scope": 1, "themes": 1, "direction": 1, "move_1d": 1}).to_list(length=None)
    table = compute_weights(rows)
    for key, value in table.items():
        await db["news_theme_weights"].replace_one({"_id": key}, {**value, "at": now}, upsert=True)
    await redis.set(WEIGHTS_KEY, json.dumps({k: v["weight"] for k, v in table.items()}))
    logger.info("news theme weights: %d from %d outcome(s)", len(table), len(rows))
    return table


async def load_weights(redis) -> dict[str, float]:
    try:
        raw = await redis.get(WEIGHTS_KEY)
        return json.loads(raw) if raw else {}
    except Exception as exc:
        logger.warning("news theme weights unavailable: %s", exc)
        return {}


async def loop(db, redis) -> None:
    await record(db, redis)
    await measure(db, redis)
    await weights(db, redis)
