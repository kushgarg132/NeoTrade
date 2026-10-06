"""Live facts for the handbook's panels (GET /system/status, admin-only).

One block per panel; each is computed on its own, and a block that raises is
reported as {"error": ...} so one broken source never blanks the page.
Cached CACHE_SECONDS per worker."""

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

from backend.configs.settings import settings
from backend.engine.session import IST
from backend.system.jobs import DAILY_PASS, DATA_QUALITY, LOOPS, last_runs

STARTED_AT = datetime.now(timezone.utc).isoformat()
CACHE_SECONDS = 30
_CACHE: dict = {}  # {"at": monotonic, "body": dict}

COLLECTIONS = ("users", "journal_trades", "paper_trades", "paper_positions", "suggestions",
               "portfolio_snapshots", "news_items", "instruments", "backlog")
BROKERS = ("kite", "upstox", "angel_one")


def _iso(value):
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


async def _deploy(db, redis) -> dict:
    return {"backend_sha": os.environ.get("GIT_SHA") or None, "backend_started_at": STARTED_AT}


async def _jobs(db, redis) -> dict:
    from backend.datalayer.worker import heartbeat_ages
    from backend.runs import ALIVE_KEY
    from backend.scheduler import seconds_until_next_run

    runs = await last_runs(redis, [DAILY_PASS, DATA_QUALITY, *LOOPS])
    now = datetime.now(timezone.utc)
    return {
        "daily_pass": runs[DAILY_PASS],
        "data_quality": runs[DATA_QUALITY],
        "next_daily_pass_at": (now + timedelta(seconds=seconds_until_next_run(now))).isoformat(),
        "loops": {name: runs[name] for name in LOOPS},
        "ingest": await heartbeat_ages(redis),
        "workers_alive": len([k async for k in redis.scan_iter(match=ALIVE_KEY.format("*"))]),
    }


async def _news(db, redis) -> dict:
    from backend.datalayer.news import COLLECTION, NEW, TRIAGED

    items = db[COLLECTION]
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    counts = await items.aggregate([
        {"$match": {"published_at": {"$gte": since}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]).to_list(length=None)
    newest = await items.find_one({}, {"published_at": 1}, sort=[("published_at", -1)])
    material = await items.find_one({"material": True}, {"title": 1, "published_at": 1}, sort=[("published_at", -1)])
    return {
        "last_24h": {row["_id"]: row["n"] for row in counts},
        "newest_at": _iso((newest or {}).get("published_at")),
        "unscored": await items.count_documents({"status": {"$in": [NEW, TRIAGED]}}),
        "last_material": material and {"title": material["title"], "at": _iso(material.get("published_at"))},
    }


async def _data(db, redis) -> dict:
    out: dict = {"collections": {name: await db[name].estimated_document_count() for name in COLLECTIONS}}
    try:
        stats = await db.command("dbStats")
        out["atlas"] = {"data_bytes": stats.get("dataSize"), "storage_bytes": stats.get("storageSize")}
    except Exception as exc:
        out["atlas"] = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        out["redis"] = {"keys": await redis.dbsize(), "memory": (await redis.info("memory")).get("used_memory_human")}
    except Exception as exc:
        out["redis"] = {"error": f"{type(exc).__name__}: {exc}"}
    out["broker_sessions"] = {
        broker: len([k async for k in redis.scan_iter(match=f"broker:*:{broker}:access_token")]) for broker in BROKERS
    }
    newest = await db["instruments"].find_one({}, {"_id": 1}, sort=[("_id", -1)])
    out["instruments"] = {
        "count": await db["instruments"].estimated_document_count(),
        "last_added_at": newest["_id"].generation_time.isoformat() if newest and hasattr(newest["_id"], "generation_time") else None,
    }
    return out


async def _ai(db, redis) -> dict:
    from backend.routers.settings import UsageUnavailable, fetch_feature_usage, fetch_usage
    from backend.app_settings import AppSettingsStore

    day = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
    try:
        usage = await fetch_usage()
    except UsageUnavailable as exc:
        usage = {"error": exc.detail}
    return {
        "news_calls_today": int(await redis.get(f"news:deep_calls:{day}") or 0),
        "news_calls_limit": settings.NEWS_LLM_CALLS_PER_DAY,
        "plan_calls_today": int(await redis.get(f"plan:calls:{day}") or 0),
        "plan_calls_limit": settings.PLAN_LLM_CALLS_PER_DAY,
        "usage": usage,
        "features": await fetch_feature_usage(),
        "features_off": await AppSettingsStore(db).get_features_off(),
    }


BLOCKS = {"deploy": _deploy, "jobs": _jobs, "news": _news, "data": _data, "ai": _ai}


async def build_status(db, redis) -> dict:
    results = await asyncio.gather(*(block(db, redis) for block in BLOCKS.values()), return_exceptions=True)
    out = {"as_of": datetime.now(timezone.utc).isoformat()}
    for name, result in zip(BLOCKS, results):
        out[name] = {"error": f"{type(result).__name__}: {result}"} if isinstance(result, Exception) else result
    return out


async def cached_status(db, redis) -> dict:
    if _CACHE and time.monotonic() - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["body"]
    body = await build_status(db, redis)
    _CACHE.update(at=time.monotonic(), body=body)
    return body
