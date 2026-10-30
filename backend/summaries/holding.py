"""Ideas > Your holdings: a one-line "what this means for you" under each bad-news and
results-soon action (position size, the risk, what to watch). Actions are derived on
demand (mine/actions.py), so a pass every 30 minutes builds the user's list and writes a
note for each such action that has none; the note is cached by the action's id, which
pins the instance. Feature `news`, tier `fast`; 4 new notes a run and 12 a day per user."""

import logging
from datetime import datetime, time
from typing import Optional

from backend.engine.session import IST
from backend.prompts import render
from backend.summaries import core

logger = logging.getLogger(__name__)

KIND, KINDS = "holding", {"bad_news", "results_soon"}
RUN_EVERY, PER_RUN, PER_DAY, TTL = 1800, 4, 12, 15 * 86_400
WINDOW = (time(8, 45), time(22, 0))


def rupees(x: Optional[float]) -> Optional[str]:
    """₹ with Indian grouping, whole rupees under ₹1,000 kept to the paisa: 696000 -> "₹6,96,000", 237.6 -> "₹237.60".
    Facts reach the model as the reader should see them, since it copies figures exactly (6960.0 came back raw)."""
    if x is None:
        return None
    if abs(x) < 1000:
        return f"{'-' if x < 0 else ''}₹{abs(x):.2f}"
    whole = f"{abs(round(x)):d}"
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        head, groups = head[:-2], [head[-2:]] + groups
    return f"{'-' if x < 0 else ''}₹{','.join(([head] if head else []) + groups + [tail])}"


def _pct(x: Optional[float], sign: bool = False) -> Optional[str]:
    return None if x is None else f"{x:+.1f}%" if sign else f"{x:.1f}%"


async def _position(db, redis, user_id: str, symbol: str) -> Optional[dict]:
    from backend.ai.facts.user import portfolio

    p = await portfolio(db, redis, user_id, account="mine")
    row = next((h for h in p.get("holdings") or [] if h.get("symbol") == symbol), None)
    if not row:
        return None
    qty = row.get("quantity")
    return {"holding": {"symbol": row.get("symbol"), "shares": int(qty) if qty is not None and qty == int(qty) else qty,
                        "average_price": rupees(row.get("avg_price")), "value": rupees(row.get("value")),
                        "gain_overall": _pct(row.get("pnl_pct"), sign=True), "share_of_account": _pct(row.get("weight_pct"))},
            "account_value": rupees((p.get("totals") or {}).get("value"))}


async def note_for(db, redis, user_id: str, action: dict):
    """The note for one action, written once (the action id is the period key)."""
    async def build():
        from backend.mine.thesis import ThesisStore

        position = await _position(db, redis, user_id, action["symbol"])
        if position is None:
            return None  # not in the last review's holdings: nothing to size it against
        t = (await ThesisStore(db).get(user_id, action["symbol"])) or {}
        thesis = {k: rupees(t[k]) if k in ("stop", "target") and isinstance(t[k], (int, float)) else t[k]
                  for k in ("why", "stop", "target", "review_by") if t.get(k)}
        facts = {"item": {k: action[k] for k in ("kind", "title", "detail")}, "position": position, "thesis": thesis}
        system, prompt = render(
            "summary_holding", item=core.as_facts(facts["item"]), position=core.as_facts(position),
            thesis=core.as_facts(thesis) if thesis else "none written")
        return system, prompt, facts

    return await core.produce(db, redis, user_id, KIND, action["id"], build, tier="fast", feature="news",
                              ttl=TTL, max_lines=1)


async def run_user(db, redis, user_id: str, now: datetime) -> int:
    from backend.mine import actions
    from backend.portfolio import digest

    local = now.astimezone(IST)
    if not WINDOW[0] <= local.time() < WINDOW[1]:
        return 0
    if not await redis.set(f"summary:holding:run:{user_id}", "1", nx=True, ex=RUN_EVERY):
        return 0
    todo = [a for a in await actions.build(db, user_id, now, await digest.verdicts_visible(db, user_id))
            if a["kind"] in KINDS]
    have = {d["key"] async for d in db[core.COLLECTION].find(
        {"user_id": user_id, "kind": KIND, "key": {"$in": [a["id"] for a in todo]}}, {"key": 1})}
    day = f"summary:holding:day:{user_id}:{local.date().isoformat()}"
    written = 0
    for a in todo:
        if a["id"] in have or written >= PER_RUN or await redis.get(core.claim_key(user_id, KIND, a["id"])):
            continue  # done, or tried lately (a failed try backs off): no call, so it does not count
        if int(await redis.incrby(day, 1)) > PER_DAY:
            break
        await redis.expire(day, 2 * 86_400)
        if await note_for(db, redis, user_id, a):
            written += 1
        elif not await redis.get(core.claim_key(user_id, KIND, a["id"])):  # built nothing: no model call was made
            await redis.incrby(day, -1)
    return written


async def run_all(db, redis, now: datetime) -> int:
    from backend.portfolio import digest

    total = 0
    for user_id in await digest._users(db):
        try:
            total += await run_user(db, redis, user_id, now)
        except Exception as exc:
            logger.warning("holding notes failed for %s: %s", user_id, exc)
    return total
