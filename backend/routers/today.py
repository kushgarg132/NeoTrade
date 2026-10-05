"""/today -- everything the Today page needs in one call: market and broker
status, what needs the user, today's P&L for their own money and the AI's,
the autopilot's last moves, and how far setup has got. Each part is
computed on its own; one that fails comes back null with its error, and
the rest still render."""

import logging
import time as clock
from datetime import datetime, time, timezone
from typing import Optional

from fastapi import APIRouter, Depends

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.engine.session import IST

router = APIRouter(prefix="/today", tags=["Today"])
logger = logging.getLogger(__name__)
NAMES = {"kite": "Kite", "upstox": "Upstox", "angel_one": "Angel One"}
MAX_PROPOSALS = 5
STATE_TTL = 60  # seconds a broker-session check is reused: Today polls every minute
_STATE_CACHE: dict = {}  # user_id -> (checked_at, roles tuple, {role: info})


async def _default_broker_states(user_id: str, brokers: list[str]) -> dict[str, str]:
    from backend.auth.broker_credentials import get_credential_store
    from backend.brokers.registry import get_broker_adapter

    states = {}
    for broker in brokers:
        adapter = await get_broker_adapter(broker, user_id, get_credential_store(), db.redis)
        states[broker] = (await adapter.state()).value
    return states


def get_broker_states():
    """Injected so tests can fake broker sessions."""
    return _default_broker_states


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _accounts(roles: dict, user_id: str, broker_states) -> dict:
    """Each role's broker session. Checking one can call the broker (Kite's
    profile endpoint), so a result is reused for STATE_TTL seconds."""
    key = tuple(sorted(roles.items()))
    cached = _STATE_CACHE.get(user_id)
    if cached and cached[1] == key and clock.monotonic() - cached[0] < STATE_TTL:
        return cached[2]
    states = await broker_states(user_id, sorted(roles))
    accounts = {role: {"broker": broker, "state": states.get(broker)} for broker, role in roles.items()}
    _STATE_CACHE[user_id] = (clock.monotonic(), key, accounts)
    return accounts


async def _needs_you(user_id: str, accounts: Optional[dict], kill: Optional[dict], now: datetime) -> list[dict]:
    from backend.guardrails.store import GuardrailStore

    items = []
    for role, info in (accounts or {}).items():
        if info["state"] != "ACTIVE":
            label = "the AI account" if role == "ai" else "your account"
            items.append({"kind": "login", "title": f"Log in to {NAMES.get(info['broker'], info['broker'])} ({label})",
                          "detail": "Broker sessions expire every day.", "link": "/settings?tab=accounts"})
    if kill and kill.get("tripped"):
        items.append({"kind": "kill_switch", "title": "Daily loss limit hit: live trading stopped",
                      "detail": kill.get("reason") or "", "link": "/settings?tab=safety"})
    pending = await db.db["suggestions"].find({"user_id": user_id, "status": "PENDING"}).to_list(length=200)
    pending.sort(key=lambda s: _aware(s.get("expires_at")) or now)
    for s in pending[:MAX_PROPOSALS]:
        items.append({"kind": "proposal", "title": f"{s.get('side', '')} {s.get('quantity', 0):g} {s['symbol']}",
                      "detail": s.get("mode", "").title(), "expires_at": _aware(s.get("expires_at")),
                      "link": "/ai/decisions"})
    async for card in db.db["chat_actions"].find({"user_id": user_id, "status": "PROPOSED"}):
        if (_aware(card.get("expires_at")) or now) >= now:
            items.append({"kind": "card", "title": card.get("summary", "A card waits for you"),
                          "detail": "Confirm or cancel it in chat.", "expires_at": _aware(card.get("expires_at"))})
    for alert in await GuardrailStore(db.db).events_for(user_id, now.astimezone(IST).date()):
        items.append({"kind": "guardrail", "title": alert.get("title", "Guardrail alert"),
                      "detail": alert.get("detail", ""), "link": "/settings?tab=safety"})
    return items


async def _pnl_today(user_id: str, roles: dict, now: datetime) -> dict:
    from backend.autopilot.service import ledger_user
    from backend.brokers.roles import brokers_for
    from backend.journal.roundtrips import build_round_trips
    from backend.journal.store import JournalStore

    day_start = datetime.combine(now.astimezone(IST).date(), time(0, 0), tzinfo=IST)
    mine_brokers = brokers_for(roles, "mine")
    # Round trips over the whole history (a position bought before today and
    # sold today is today's P&L), kept if they closed today.
    trades = [t for t in await JournalStore(db.db).list_trades(user_id)
              if not mine_brokers or t.get("broker") in mine_brokers]
    mine = sum(t["pnl"] for t in build_round_trips(trades)
               if t.get("pnl") is not None and (_aware(t.get("closed_at")) or day_start) >= day_start)
    ai = 0.0
    async for t in db.db["paper_trades"].find({"user_id": ledger_user(user_id)}):
        if t.get("status") == "CLOSED" and (_aware(t.get("exit_at")) or day_start) >= day_start:
            ai += t.get("realized_pnl") or 0.0
    return {"mine": round(mine, 2), "ai": round(ai, 2)}


async def _setup(user_id: str, prefs: dict) -> dict:
    from backend.profile.store import ProfileStore

    roles = prefs.get("broker_roles") or {}
    has_creds = {d["broker"] async for d in db.db["broker_credentials"].find({"user_id": user_id}, {"broker": 1})}
    channel = await db.db["alert_channels"].find_one({"_id": user_id}) or {}
    profile = await ProfileStore(db.db).get(user_id)
    steps = [
        ("connect_mine", "Connect your broker", any(b in has_creds for b, r in roles.items() if r == "mine"), "/settings?tab=accounts"),
        ("connect_ai", "Connect the AI's broker", any(b in has_creds for b, r in roles.items() if r == "ai"), "/settings?tab=accounts"),
        ("roles", "Choose which account is yours and which is the AI's", {"ai", "mine"} <= set(roles.values()), "/settings?tab=accounts"),
        ("daily_loss", "Set a daily loss limit", bool(prefs.get("guardrails_enabled")) and (prefs.get("daily_loss_limit") or 0) > 0, "/settings?tab=safety"),
        ("telegram", "Link Telegram for alerts", bool(channel.get("telegram_chat_id")), "/settings?tab=safety"),
        ("profile", "Tell the AI about yourself", sum(1 for k, v in profile.items() if k != "memories" and v) >= 3, "/profile"),
    ]
    rows = [{"id": i, "label": label, "done": bool(done), "link": link} for i, label, done, link in steps]
    return {"done": sum(r["done"] for r in rows), "total": len(rows), "steps": rows}


async def _autopilot(user_id: str, prefs: dict) -> dict:
    """The AI account's autopilot at a glance: switch, mode, and capital in use
    (open positions at entry price -- no market call)."""
    from backend.autopilot.service import ledger_user

    deployed = 0.0
    async for t in db.db["paper_trades"].find({"user_id": ledger_user(user_id), "status": "OPEN"}):
        deployed += (t.get("quantity") or 0) * (t.get("entry_price") or 0)
    return {"enabled": bool(prefs.get("autopilot_enabled")), "live": bool(prefs.get("autopilot_live")),
            "capital": prefs.get("autopilot_capital"), "deployed": round(deployed, 2)}


@router.get("")
async def today(user: User = Depends(get_current_user), broker_states=Depends(get_broker_states)):
    from backend.engine.autorun import in_session
    from backend.prefs import PrefsStore
    from backend.risk.kill_switch import KillSwitchStore

    now = datetime.now(timezone.utc)
    prefs = await PrefsStore(db.db).get(user.id)
    roles = prefs.get("broker_roles") or {}
    errors: dict[str, str] = {}

    async def part(name, coro):
        try:
            return await coro
        except Exception as exc:
            logger.warning("today: %s failed for %s: %s", name, user.id, exc)
            errors[name] = str(exc)
            return None

    accounts = await part("accounts", _accounts(roles, user.id, broker_states))
    tripped = await part("kill_switch", KillSwitchStore(db.db).is_tripped(user.id, now.astimezone(IST).date()))
    kill = {"tripped": bool(tripped), "reason": (tripped or {}).get("reason")} if "kill_switch" not in errors else None
    log = await part("ai_activity", db.db["autopilot_log"].find({"user_id": user.id}, {"_id": 0, "user_id": 0})
                     .sort("at", -1).limit(5).to_list(length=5))
    for row in log or []:
        row["at"] = _aware(row.get("at"))  # Mongo hands back naive UTC; say so to the browser
    return {
        "market": {"open": in_session(now), "as_of": now},
        "accounts": accounts,
        "live_armed": {"autopilot": bool(prefs.get("autopilot_enabled") and prefs.get("autopilot_live")),
                       "strategies": prefs.get("live_strategies") or []},
        "kill_switch": kill,
        "needs_you": await part("needs_you", _needs_you(user.id, accounts, kill, now)) or [],
        "pnl_today": await part("pnl_today", _pnl_today(user.id, roles, now)),
        "ai_activity": log,
        "autopilot": await part("autopilot", _autopilot(user.id, prefs)),
        "setup": await part("setup", _setup(user.id, prefs)),
        "errors": errors,
    }
