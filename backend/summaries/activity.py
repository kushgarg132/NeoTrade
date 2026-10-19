"""AI > Activity: "what the AI did today and why", once per user per day after the 16:00 pass,
from the autopilot log, the day's game plan and the AI book's closed P&L. Feature `plan`,
standard tier. Users with no order, refusal or plan today get nothing."""

import logging
from datetime import datetime, time

from backend.engine.session import IST
from backend.prompts import render
from backend.summaries import core

logger = logging.getLogger(__name__)

KIND, TTL, MAX_ROWS = "activity", 30 * 3600, 30
ROW_KEYS = ("status", "side", "quantity", "symbol", "source", "mode", "reason")
PLAN_KEYS = ("trigger", "skip_day", "risk_multiplier", "max_positions", "rationale")


async def _day_rows(db, user_id: str, start: datetime) -> list[dict]:
    rows = await db["autopilot_log"].find({"user_id": user_id, "at": {"$gte": start}}).sort("at", 1) \
        .to_list(length=MAX_ROWS)
    return [{k: r.get(k) for k in ROW_KEYS} for r in rows]


async def generate(db, redis, user_id: str, now: datetime):
    from backend.ai.facts.user import game_plan
    from backend.portfolio.digest import pnl_since
    from backend.prefs import PrefsStore

    local = now.astimezone(IST)
    start, key = datetime.combine(local.date(), time(0, 0), tzinfo=IST), local.date().isoformat()

    async def build():
        rows = await _day_rows(db, user_id, start)
        plan = (await game_plan(db, redis, user_id)).get("plan")
        if not rows and not plan:
            return None  # the AI did nothing and planned nothing: nothing to explain
        roles = (await PrefsStore(db).get(user_id)).get("broker_roles") or {}
        pnl = await pnl_since(db, user_id, roles, start)
        allow = plan.get("allow") or [] if plan else []
        facts = {"orders": rows,
                 "plan": {k: plan.get(k) for k in PLAN_KEYS} | {
                     "allowed_symbols": sorted(a["symbol"] for a in allow)[:15],
                     "allowed_strategies": sorted({n for a in allow for n in a.get("strategies") or []})}
                 if plan else None,
                 "result": {"ai_net_pnl": pnl["ai"], "ai_charges": pnl["ai_charges"]}}
        system, prompt = render(
            "summary_activity", day=local.strftime("%a %d %b %Y"),
            orders=core.as_facts(rows) if rows else "none: no orders or refusals today",
            plan=core.as_facts(facts["plan"]) if plan else "no game plan was built today",
            result=core.as_facts(facts["result"]))
        return system, prompt, facts

    return await core.produce(db, redis, user_id, KIND, key, build, tier="standard",
                              feature="plan", ttl=TTL)


async def run_all(db, redis, now: datetime) -> int:
    """After the close, every user the AI acted or planned for today."""
    local = now.astimezone(IST)
    start = datetime.combine(local.date(), time(0, 0), tzinfo=IST)
    users = set(await db["autopilot_log"].distinct("user_id", {"at": {"$gte": start}}))
    users |= set(await db["trade_plans"].distinct("user_id", {"date": local.date().isoformat()}))
    written = 0
    for user_id in sorted(users):
        try:
            written += bool(await generate(db, redis, user_id, now))
        except Exception as exc:
            logger.warning("activity summary failed for %s: %s", user_id, exc)
    return written
