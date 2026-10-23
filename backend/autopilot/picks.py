"""The AI account trades Picks (backend/forecast/picks.py) as their forward
record (owner decision 2026-10-17): each stored pick is bought at the next
session's morning pass and sold from 15:15 on its due date (the close of its
horizon), CNC, long only.

Every order goes through `service.submit`, so the fence (per-trade cap, max
invested, trades a day, the switch, Nifty 200) and the kill switch apply and
fills land in the AI book like any autopilot order -- tagged `autopilot:picks`,
strategy `picks:<setup>`, the pick's id and due date on the trade's context.
Only for admin users while Picks is admin-only, and quietly: nothing about
Picks reaches Telegram.

Paper unless the forward record passes `forecast.picks.live_refusal` AND the
owner turned on both `picks_live` and the autopilot's live mode."""

import logging
from datetime import datetime
from typing import Optional

from backend.autopilot import fence, service
from backend.core.models import Side
from backend.engine.session import IST, is_past_square_off_time
from backend.forecast.picks import PICKS, live_refusal
from backend.marks import ORDER_MAX_AGE_SECONDS, mark_prices
from backend.prefs import PrefsStore

logger = logging.getLogger(__name__)
PREFIX = "picks:"


async def _admin(db, user_id: str) -> bool:
    return ((await db["users"].find_one({"id": user_id}, {"role": 1})) or {}).get("role") == "admin"


async def live_allowed(db, prefs: dict) -> bool:
    if not (prefs.get("picks_live") and prefs.get("autopilot_live")):
        return False
    why = live_refusal(await db[PICKS].find({"outcome": {"$ne": None}}).to_list(length=None))
    if why:
        logger.info("picks stay on paper: %s", why)
    return why is None


async def enter(db, redis, user_id: str, now: datetime) -> list[dict]:
    """Buys the last session's picks not yet traded, best first, each sized
    to the per-trade cap in force. Returns each pick's submit result."""
    if not await _admin(db, user_id):
        return []
    today = now.astimezone(IST).date().isoformat()
    latest = await db[PICKS].find_one({"date": {"$lt": today}}, {"date": 1}, sort=[("date", -1)])
    if latest is None:
        return []
    # ponytail: a pick still before its due date is bought even if a missed
    # morning made it a session late; exact "next open" needs a holiday calendar.
    picks = [p for p in await db[PICKS].find({"date": latest["date"]}).to_list(length=None)
             if p["due_date"] > today and not p.get("backfilled")]  # backfilled: hindsight, never bought
    traded = set(await db["paper_trades"].distinct(
        "context.pick_id", {"user_id": {"$in": [user_id, service.ledger_user(user_id)]},
                            "context.pick_id": {"$in": [p["_id"] for p in picks]}}))
    picks = [p for p in picks if p["_id"] not in traded]
    if not picks:
        return []
    prefs = await PrefsStore(db).get(user_id)
    live = await live_allowed(db, prefs)
    cap = fence.trade_cap(prefs, (await service.regime_now(redis)).get("label"))
    marks = await mark_prices(db, {p["symbol"] for p in picks}, max_age_seconds=ORDER_MAX_AGE_SECONDS)
    picks.sort(key=lambda p: (p["median_excess"] * p["p_beat_nifty"], p["strength"]), reverse=True)
    results = []
    for p in picks:
        price = marks.get(p["symbol"])
        # Sizing as the autopilot sizes proposals: whole shares inside the
        # per-trade cap; the fence enforces max invested and trades a day.
        quantity = int(cap // price) if price else 0
        if quantity < 1:
            results.append({"pick": p["_id"], "status": "SKIPPED", "reason": "under one share inside the cap"})
            continue
        result = await service.submit(db, redis, user_id, service.AutopilotOrder(
            symbol=p["symbol"], side=Side.BUY, quantity=quantity, product="CNC", source="picks",
            reason=f"Pick: {p['label']} (P(up) {p['p_up']:.0%}, {p['horizon']}-day horizon).",
            strategy=f"{PREFIX}{p['setup']}", live=live,
            context={"pick_id": p["_id"], "due_date": p["due_date"], "strength": p["strength"],
                     "reason_codes": [p["setup"]]}), now=now, quiet=True)
        results.append({"pick": p["_id"], **result})
    return results


def _due(trade: dict, now: datetime) -> bool:
    due, today = trade["context"]["due_date"], now.astimezone(IST).date().isoformat()
    return due < today or (due == today and is_past_square_off_time(now))


async def exit_due(db, redis, user_id: str, now: datetime) -> list[dict]:
    """Sells each open pick trade at the close of its horizon (from 15:15 on
    its due date, or at once if that passed). Exits are never admin-gated."""
    trades = [t for t in await service.open_trades(db, user_id)
              if (t.get("strategy") or "").startswith(PREFIX) and (t.get("context") or {}).get("pick_id")
              and t["side"] == "BUY" and _due(t, now)]
    results = []
    for t in trades:
        result = await service.submit(db, redis, user_id, service.AutopilotOrder(
            symbol=t["symbol"], side=Side.SELL, quantity=int(t["quantity"]), product="CNC", source="picks",
            reason="Pick's horizon is over: sold at the close.", strategy=t["strategy"],
            live=t["user_id"] == service.ledger_user(user_id)), now=now, quiet=True)
        results.append({"pick": t["context"]["pick_id"], **result})
    return results
