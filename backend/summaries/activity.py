"""AI > Activity: "what the AI did today and why", once per user per day after the 16:00 pass,
from the autopilot log, the day's rotation plan and the AI book's closed P&L. Feature `plan`,
standard tier. Users with no order, refusal or plan today get nothing."""

import logging
from datetime import datetime, time
from typing import Optional

from backend.engine.session import IST
from backend.prompts import render
from backend.summaries import core
from backend.summaries.holding import rupees

logger = logging.getLogger(__name__)

KIND, TTL, MAX_ROWS = "activity", 30 * 3600, 30
ROW_KEYS = ("status", "side", "quantity", "symbol", "source", "mode", "reason")


async def _rotation(db, user_id: str, day: str) -> Optional[dict]:
    """The day's rotation plan (`autopilot/rotation.py::plan`) in words the note can copy."""
    p = await db["rotation_plans"].find_one({"user_id": user_id, "date": day})
    if not p:
        return None
    gap = p.get("nifty_vs_200dma")
    return {"holding cash because the Nifty is under its 200-day average": bool(p.get("risk_off")),
            "share of the book to invest": f"{(p.get('exposure') or 0) * 100:.0f}%",
            "Nifty against its 200-day average": None if gap is None else f"{gap * 100:+.2f}%",
            "sells due": [s["symbol"] for s in p.get("sells") or []], "buys due": [b["symbol"] for b in p.get("buys") or []],
            "blocked by news or a results date": p.get("news_vetoed") or {},
            "next rebalance": p.get("next_rebalance"), "real money": bool(p.get("live"))}


async def _day_rows(db, user_id: str, start: datetime) -> list[dict]:
    rows = await db["autopilot_log"].find({"user_id": user_id, "at": {"$gte": start}}).sort("at", 1) \
        .to_list(length=MAX_ROWS)
    return [{k: r.get(k) for k in ROW_KEYS} for r in rows]


async def generate(db, redis, user_id: str, now: datetime):
    from backend.portfolio.digest import pnl_since
    from backend.prefs import PrefsStore

    local = now.astimezone(IST)
    start, key = datetime.combine(local.date(), time(0, 0), tzinfo=IST), local.date().isoformat()

    async def build():
        rows = await _day_rows(db, user_id, start)
        rotation = await _rotation(db, user_id, key)
        if not rows and not rotation:
            return None  # the AI did nothing and planned nothing: nothing to explain
        roles = (await PrefsStore(db).get(user_id)).get("broker_roles") or {}
        pnl = await pnl_since(db, user_id, roles, start)
        facts = {"orders": rows, "rotation": rotation,
                 "result": {"net result": rupees(pnl["ai"]), "charges": rupees(pnl["ai_charges"])}}
        system, prompt = render(
            "summary_activity", day=local.strftime("%a %d %b %Y"),
            orders=core.as_facts(rows) if rows else "none: no orders or refusals today",
            rotation=core.as_facts(rotation) if rotation else "no rotation plan today",
            result=core.as_facts(facts["result"]))
        return system, prompt, facts

    return await core.produce(db, redis, user_id, KIND, key, build, task="summary.activity", ttl=TTL)


async def run_all(db, redis, now: datetime) -> int:
    """After the close, every user the AI acted or planned for today."""
    local = now.astimezone(IST)
    start = datetime.combine(local.date(), time(0, 0), tzinfo=IST)
    users = set(await db["autopilot_log"].distinct("user_id", {"at": {"$gte": start}}))
    users |= set(await db["rotation_plans"].distinct("user_id", {"date": local.date().isoformat()}))
    written = 0
    for user_id in sorted(users):
        try:
            written += bool(await generate(db, redis, user_id, now))
        except Exception as exc:
            logger.warning("activity summary failed for %s: %s", user_id, exc)
    return written
