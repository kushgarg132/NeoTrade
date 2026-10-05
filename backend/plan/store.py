"""Game plans: every version in Mongo `trade_plans` (one doc per user,
IST day and version), the current one mirrored to Redis for the engine's
per-bar reads, and the daily budget of LLM calls spent on plans."""

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from backend.configs.settings import settings
from backend.engine.session import IST
from backend.plan.validate import TradePlan

COLLECTION = "trade_plans"
KEY = "plan:{}:{}"
CALLS_KEY = "plan:calls:{}"


def _ttl(day: date, now: datetime) -> int:
    expires = datetime.combine(day + timedelta(days=1), time(1, 0), IST)
    return max(60, int((expires - now).total_seconds()))


async def save(db, redis, user_id: str, day: date, plan: TradePlan, now: datetime) -> dict:
    last = await db[COLLECTION].find_one({"user_id": user_id, "date": day.isoformat()}, sort=[("version", -1)])
    doc = {"user_id": user_id, "date": day.isoformat(), "version": (last["version"] + 1) if last else 1,
           "at": now, **plan.model_dump()}
    await db[COLLECTION].insert_one(dict(doc))
    if redis is not None:
        await redis.set(KEY.format(user_id, day.isoformat()), json.dumps({**doc, "at": now.isoformat()}),
                        ex=_ttl(day, now))
    return doc


async def current(redis, user_id: str, day: date) -> Optional[dict]:
    raw = await redis.get(KEY.format(user_id, day.isoformat())) if redis is not None else None
    return json.loads(raw) if raw else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def versions(db, user_id: str, day: date) -> list[dict]:
    docs = await db[COLLECTION].find({"user_id": user_id, "date": day.isoformat()}, {"_id": 0}) \
        .sort("version", 1).to_list(length=None)
    return [{**d, "at": _aware(d["at"])} for d in docs]


async def reserve_call(redis, day: date) -> bool:
    """One LLM call from today's plan allowance; False once it is spent."""
    key = CALLS_KEY.format(day.isoformat())
    used = int(await redis.incrby(key, 1))
    await redis.expire(key, 2 * 86400)
    if used > settings.PLAN_LLM_CALLS_PER_DAY:
        await redis.incrby(key, -1)
        return False
    return True
