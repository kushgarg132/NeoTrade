"""Exits for the Picks trades the AI account still holds. Since 2026-11-02 the
autopilot buys only the weekly rotation (backend/autopilot/rotation.py); Picks
stays admin research. Each pick trade is sold from 15:15 on its due date (the
close of its horizon, the exit the study grades), CNC, long only. Its stop and target
(`forecast.picks.levels`, moved to the fill by `suggestions.exits.anchored`)
are stored and traded only while the study's `levels_exit` says they beat the
horizon exit for that setup; a trade without stored levels keeps the time exit.

Every exit goes through `service.submit` (exits are never blocked by caps or
the switch), quietly: nothing about Picks reaches Telegram."""

import logging
from datetime import datetime

from backend.autopilot import service
from backend.core.models import Side
from backend.engine.session import IST, is_past_square_off_time
from backend.forecast.picks import STUDY
from backend.marks import mark_prices

logger = logging.getLogger(__name__)
PREFIX = "picks:"


def _levels_tested(study: dict) -> set:
    """Setups whose stop/target beat the horizon close in the study (`study.levels_exit`): trade the exit
    that was tested. The 2026-10-27 run found the levels worse in every setup (breakout t -5.2)."""
    return {s["setup"] for s in (study or {}).get("setups", []) if (s.get("levels_exit") or {}).get("better")}


def _due(trade: dict, now: datetime) -> bool:
    due, today = trade["context"]["due_date"], now.astimezone(IST).date().isoformat()
    return due < today or (due == today and is_past_square_off_time(now))


async def exit_due(db, redis, user_id: str, now: datetime) -> list[dict]:
    """Sells each open pick trade whose mark crossed its fill-anchored stop or
    target, or at the close of its horizon (from 15:15 on its due date, or at
    once if that passed). Exits are never admin-gated."""
    from backend.suggestions.exits import anchored, breach

    trades = [t for t in await service.open_trades(db, user_id)
              if (t.get("strategy") or "").startswith(PREFIX) and (t.get("context") or {}).get("pick_id")
              and t["side"] == "BUY"]
    tested = _levels_tested(await db[STUDY].find_one({"_id": "latest"}))  # trades opened before the test too
    leveled = [t for t in trades if (t["context"].get("stop") or t["context"].get("target"))
               and t["strategy"][len(PREFIX):] in tested]
    marks = await mark_prices(db, {t["symbol"] for t in leveled}) if leveled else {}
    results = []
    for t in trades:
        c, mark = t["context"], marks.get(t["symbol"])
        why = "horizon" if _due(t, now) else t in leveled and mark and breach(
            mark, anchored(c.get("stop"), c.get("entry_ref"), t.get("entry_price")),
            anchored(c.get("target"), c.get("entry_ref"), t.get("entry_price")))
        if not why:
            continue
        text = "Pick's horizon is over: sold at the close." if why == "horizon" else f"Pick hit its {why}."
        result = await service.submit(db, redis, user_id, service.AutopilotOrder(
            symbol=t["symbol"], side=Side.SELL, quantity=int(t["quantity"]), product="CNC", source="picks",
            reason=text, strategy=t["strategy"], live=t["user_id"] == service.ledger_user(user_id)),
            now=now, quiet=True)
        results.append({"pick": c["pick_id"], "why": why, **result})
    return results
