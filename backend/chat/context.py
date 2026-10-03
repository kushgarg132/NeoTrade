"""The day snapshot every chat message carries: a short, fresh summary of
one user's account, so the commonest questions are answered without a tool
call. Every read is scoped by user_id; a section that fails is reported as
unavailable instead of failing the answer."""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from backend.engine.autorun import in_session
from backend.engine.session import IST
from backend.guardrails.store import GuardrailStore
from backend.journal.roundtrips import build_round_trips, daily_pnl
from backend.journal.store import JournalStore
from backend.portfolio.service import latest_snapshot
from backend.prefs import PrefsStore
from backend.risk.kill_switch import KillSwitchStore
from backend.runs import RunStore
from backend.suggestions.store import SuggestionStore

logger = logging.getLogger(__name__)

LIMIT_KEYS = ("daily_loss_limit", "per_trade_cap", "max_trades_per_day", "auto_paper_intraday", "guardrails_enabled")


def plan_names(plan: Optional[str], heading: str) -> list[str]:
    """Stocks named in bold at the start of each bullet under the plan's
    `### <heading>` section -- the same rule the statement's glance uses."""
    for part in re.split(r"^###\s+", plan or "", flags=re.M):
        if part.lower().startswith(heading):
            return [re.sub(r"\s*\(.*$", "", m).strip() for m in re.findall(r"^\s*[-*]\s+\*\*([^*]+)\*\*", part, flags=re.M)]
    return []


async def _portfolio(db, user_id, now):
    snap = await latest_snapshot(db, user_id)
    if not snap:
        return {"as_of": None, "none": "No portfolio analysed yet"}
    totals = snap["totals"]
    return {
        "as_of": snap["at"].isoformat() if hasattr(snap["at"], "isoformat") else str(snap["at"]),
        "value": totals.get("value"), "today": totals.get("day_change"), "overall_pct": totals.get("pnl_pct"),
        "holdings": len(snap.get("holdings", [])),
        "sell_or_trim": plan_names(snap.get("plan"), "sell")[:3], "add": plan_names(snap.get("plan"), "add")[:3],
    }


async def _broker(db, user_id, now):
    calendar = daily_pnl(build_round_trips(await JournalStore(db).list_trades(user_id)))
    today = now.astimezone(IST).date().isoformat()
    month = today[:7]
    rows = [r for r in calendar if r["day"].startswith(month)]
    today_row = next((r for r in calendar if r["day"] == today), None)
    return {
        "as_of": "last journal sync, gross of charges",
        "today_pnl": (today_row or {}).get("pnl", 0.0), "today_closed": (today_row or {}).get("trips", 0),
        "month_pnl": round(sum(r["pnl"] for r in rows), 2), "month_closed": sum(r["trips"] for r in rows),
    }


async def _decisions(db, user_id, now):
    pending = await SuggestionStore(db).list(user_id, status="PENDING", limit=200)
    top = sorted(pending, key=lambda s: (s.get("score") or {}).get("final") or 0, reverse=True)[:3]
    return {
        "as_of": now.isoformat(), "pending": len(pending),
        "top": [{"id": s["id"], "symbol": s["symbol"], "side": s["side"], "mode": s["mode"],
                 "score": round((s.get("score") or {}).get("final") or 0, 2)} for s in top],
    }


async def _paper(db, user_id, now):
    runs = await RunStore(db).list_active(user_id)
    tripped = await KillSwitchStore(db).is_tripped(user_id, now.astimezone(IST).date())
    open_paper = await db["paper_positions"].count_documents(
        {"user_id": user_id, "quantity": {"$ne": 0}, "venue": {"$ne": "live"}}
    )
    return {
        "as_of": now.isoformat(),
        "running": [{"run_id": r["run_id"], "mode": r["mode"], "origin": r["params"].get("origin")} for r in runs],
        "open_paper_positions": open_paper,
        "kill_switch": {"tripped": bool(tripped), "reason": (tripped or {}).get("reason")},
    }


async def _limits(db, user_id, now):
    prefs = await PrefsStore(db).get(user_id)
    alerts = await GuardrailStore(db).events_for(user_id, now.astimezone(IST).date())
    return {
        "as_of": now.isoformat(), **{k: prefs.get(k) for k in LIMIT_KEYS},
        "alerts_today": [a.get("title") or a["key"] for a in alerts],
    }


SECTIONS = {"portfolio": _portfolio, "broker": _broker, "decisions": _decisions, "paper": _paper, "limits": _limits}


async def build_snapshot(db, redis, user_id: str, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    snapshot = {"market": {"session_open": in_session(now), "ist": now.astimezone(IST).strftime("%a %d %b %Y %H:%M IST")}}
    for name, read in SECTIONS.items():
        try:
            snapshot[name] = await read(db, user_id, now)
        except Exception as exc:
            logger.warning("chat snapshot: %s unavailable for %s: %s", name, user_id, exc)
            snapshot[name] = {"unavailable": str(exc)[:120] or type(exc).__name__}
    return snapshot


def format_snapshot(snapshot: dict) -> str:
    """One line per section, compact enough to ride with every message."""
    lines = []
    for name, section in snapshot.items():
        if "unavailable" in section:
            lines.append(f"{name}: unavailable ({section['unavailable']})")
        else:
            lines.append(f"{name}: " + "; ".join(f"{k}={v}" for k, v in section.items()))
    return "\n".join(lines)
