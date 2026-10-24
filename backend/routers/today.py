"""/today -- everything the Today page needs in one call: market and broker
status, the user's own portfolio right now (portfolio/digest.py::pulse),
what needs the user, AI against the user today and this month,
the autopilot's last moves, and how far setup has got. Each part is
computed on its own; one that fails comes back null with its error, and
the rest still render."""

import logging
import time as clock
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.core import market_calendar
from backend.core.market_calendar import market_phase
from backend.database import db
from backend.engine.session import IST

router = APIRouter(prefix="/today", tags=["Today"])
logger = logging.getLogger(__name__)
NAMES = {"kite": "Kite", "upstox": "Upstox", "angel_one": "Angel One"}
TOP_ACTIONS = 3  # Today is the glance; Mine holds the whole list
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
    profile endpoint), so a result is reused for STATE_TTL seconds -- only
    when every session is live. A logged-out one costs no broker call, and
    reusing it would hide a fresh login for up to a minute on each worker."""
    key = tuple(sorted(roles.items()))
    cached = _STATE_CACHE.get(user_id)
    if cached and cached[1] == key and clock.monotonic() - cached[0] < STATE_TTL:
        return cached[2]
    states = await broker_states(user_id, sorted(roles))
    accounts = {role: {"broker": broker, "state": states.get(broker)} for broker, role in roles.items()}
    if all(info["state"] == "ACTIVE" for info in accounts.values()):
        _STATE_CACHE[user_id] = (clock.monotonic(), key, accounts)
    else:
        _STATE_CACHE.pop(user_id, None)
    return accounts


async def _ideas(user_id: str) -> list[dict]:
    """Pending ideas for the user's own account: proven strategies only."""
    from backend.mine import actions

    return await actions.ideas(db.db, user_id)


RECON_FRESH_DAYS = 4  # a weekend plus a day: older results are not today's truth


async def _needs_you(user_id: str, accounts: Optional[dict], kill: Optional[dict], now: datetime,
                     admin: bool = False) -> list[dict]:
    """The app's own nags: logins, the kill switch, interrupted approvals,
    chat cards, guardrails, broker reconciliation, and (admin) data quality.
    Holding items (exits, verdicts, ideas) are Mine's "Needs you" list
    (mine/actions.py), read as `mine_actions`."""
    from backend.engine import broker_recon
    from backend.guardrails.store import GuardrailStore
    from backend.system import data_quality

    items = []
    for role, info in (accounts or {}).items():
        if info["state"] != "ACTIVE":
            label = "the AI account" if role == "ai" else "your account"
            items.append({"kind": "login", "title": f"Log in to {NAMES.get(info['broker'], info['broker'])} ({label})",
                          "detail": "Broker sessions expire every day.", "link": "/settings?tab=accounts"})
    if kill and kill.get("tripped"):
        items.append({"kind": "kill_switch", "title": "Daily loss limit hit: live trading stopped",
                      "detail": kill.get("reason") or "", "link": "/journal?tab=guardrails"})
    async for s in db.db["suggestions"].find({"user_id": user_id, "status": "NEEDS_REVIEW"}):
        items.append({"kind": "review", "title": f"Check {s['symbol']}: an approval was interrupted",
                      "detail": s.get("reason") or "Check your broker's order book before approving again.",
                      "link": "/journal"})
    async for card in db.db["chat_actions"].find({"user_id": user_id, "status": "PROPOSED"}):
        if (_aware(card.get("expires_at")) or now) >= now:
            items.append({"kind": "card", "title": card.get("summary", "A card waits for you"),
                          "detail": "Confirm or cancel it in chat.", "expires_at": _aware(card.get("expires_at"))})
    for alert in await GuardrailStore(db.db).events_for(user_id, now.astimezone(IST).date()):
        items.append({"kind": "guardrail", "title": alert.get("title", "Guardrail alert"),
                      "detail": alert.get("detail", ""), "link": "/journal?tab=guardrails"})
    since = now.astimezone(IST).date() - timedelta(days=RECON_FRESH_DAYS)
    if line := broker_recon.summary(await broker_recon.latest(db.db, user_id, since)):
        items.append({"kind": "reconcile", "title": "Reconciliation: broker and app records differ",
                      "detail": line, "link": "/journal"})
    if admin:
        try:  # a broken check must not hide the user's other nags
            failures = await data_quality.alerts(db.db, db.redis, now)
        except Exception as exc:
            logger.warning("today: data-quality alerts failed: %s", exc)
            failures = [f"Data-quality checks could not run: {type(exc).__name__}"]
        for failure in failures:
            items.append({"kind": "data_quality", "title": failure, "detail": "Data quality", "link": "/lab/handbook"})
    return items


async def _mine_actions(user_id: str, now: datetime) -> list[dict]:
    from backend.mine import actions
    from backend.portfolio import digest

    return await actions.build(db.db, user_id, now, await digest.verdicts_visible(db.db, user_id))


async def _setup(user_id: str, prefs: dict) -> dict:
    from backend.profile.store import ProfileStore

    roles = prefs.get("broker_roles") or {}
    has_creds = {d["broker"] async for d in db.db["broker_credentials"].find({"user_id": user_id}, {"broker": 1})}
    channel = await db.db["alert_channels"].find_one({"_id": user_id}) or {}
    profile = await ProfileStore(db.db).get(user_id)
    # No broker needed: files give holdings, journal and tax (/import).
    has_trades = await db.db["journal_trades"].find_one({"user_id": user_id}, {"_id": 1}) is not None
    has_funds = await db.db["mf_imports"].find_one({"_id": user_id}, {"_id": 1}) is not None
    steps = [
        ("import_trades", "Import your trades from a Zerodha Console file", has_trades, "/portfolio/import"),
        ("import_funds", "Import your mutual funds from a CAS statement", has_funds, "/portfolio/import"),
        ("connect_mine", "Connect your broker", any(b in has_creds for b, r in roles.items() if r == "mine"), "/settings?tab=accounts"),
        ("connect_ai", "Connect the AI's broker", any(b in has_creds for b, r in roles.items() if r == "ai"), "/settings?tab=accounts"),
        ("roles", "Choose which account is yours and which is the AI's", {"ai", "mine"} <= set(roles.values()), "/settings?tab=accounts"),
        ("daily_loss", "Turn on Watch my broker, with a daily loss limit", bool(prefs.get("guardrails_enabled")) and (prefs.get("daily_loss_limit") or 0) > 0, "/journal?tab=guardrails"),
        ("telegram", "Link Telegram for alerts", bool(channel.get("telegram_chat_id")), "/journal?tab=guardrails"),
        ("profile", "Tell the AI about yourself", sum(1 for k, v in profile.items() if k != "memories" and v) >= 3, "/profile"),
    ]
    rows = [{"id": i, "label": label, "done": bool(done), "link": link} for i, label, done, link in steps]
    return {"done": sum(r["done"] for r in rows), "total": len(rows), "steps": rows}


async def _autopilot(user_id: str, prefs: dict) -> dict:
    """The AI account's autopilot at a glance: switch, mode, its capital
    (`account_size`, the base its returns and AI-vs-you use), the exposure cap,
    and capital in use (open positions at entry price -- no market call)."""
    from backend.autopilot.service import open_trades

    deployed = 0.0
    for t in await open_trades(db.db, user_id):
        deployed += (t.get("quantity") or 0) * (t.get("entry_price") or 0)
    return {"enabled": bool(prefs.get("autopilot_enabled")), "live": bool(prefs.get("autopilot_live")),
            "capital": prefs.get("account_size"), "exposure_cap": prefs.get("max_exposure"),
            "deployed": round(deployed, 2)}


async def _backdrop(now: datetime) -> dict:
    """The ingest worker's market brief and risk regime, and the high-impact
    events in the next day. Empty parts when the worker has not run."""
    from backend.datalayer import market

    events = await market.upcoming(db.db, hours=24, now=now)
    return {**await market.backdrop(db.redis), "events": [{**e, "at": _aware(e["at"])} for e in events]}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _unjournaled(user_id: str, roles: dict, now: datetime) -> int:
    """Today's closed round trips on the user's own account with no note yet."""
    from backend.journal.accounts import brokers_of, filter_trades
    from backend.journal.roundtrips import build_round_trips
    from backend.journal.store import JournalStore

    store = JournalStore(db.db)
    trades = filter_trades(await store.list_trades(user_id), brokers_of(roles, "mine"))
    day = now.astimezone(IST).date()
    trips = [t for t in build_round_trips(trades)
             if t.get("closed_at") and _aware(t["closed_at"]).astimezone(IST).date() == day]
    notes = await store.notes_for(user_id)
    return sum(1 for t in trips if not (notes.get(t["id"]) or {}).get("note"))


async def _picks_top(user_id: str) -> list[dict]:
    """Today's Picks card: the grade-A (proven) part of the list Ideas shows."""
    from backend.routers.picks import served_today

    shown = [p for p in (await served_today(user_id))[3]["shown"] if p["grade"] == "A"]
    return [{"symbol": p["symbol"], "label": p.get("label"), "median": (p.get("expected") or {}).get("median")}
            for p in shown]


@router.get("")
async def today(user: User = Depends(get_current_user), broker_states=Depends(get_broker_states)):
    from backend.engine.autorun import in_session
    from backend.portfolio import digest
    from backend.prefs import PrefsStore
    from backend.risk.kill_switch import KillSwitchStore

    now = _now()
    phase = market_phase(now)
    admin = user.role == "admin"
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
        "phase": phase,
        "next_open": market_calendar.next_open(now),
        "premarket": await part("premarket", digest.premarket_for(db.db, user.id, now)) if phase == "pre" else None,
        "postclose": await part("postclose", digest.postclose_for(db.db, user.id, now))
        if phase in ("post", "closed") else None,
        "unjournaled": await part("unjournaled", _unjournaled(user.id, roles, now)) if phase == "post" else None,
        "picks_top": await part("picks_top", _picks_top(user.id)) if admin and phase == "pre" else None,
        "accounts": accounts,
        "live_armed": {"autopilot": bool(prefs.get("autopilot_enabled") and prefs.get("autopilot_live")),
                       "strategies": prefs.get("live_strategies") or []},
        "kill_switch": kill,
        "pulse": await part("pulse", digest.cached_pulse(db.db, user.id, now)),
        "needs_you": await part("needs_you", _needs_you(user.id, accounts, kill, now, user.role == "admin")) or [],
        "mine_actions": (acts := await part("mine_actions", _mine_actions(user.id, now)) or [])[:TOP_ACTIONS],
        "mine_actions_total": len(acts),
        # You vs Picks: admin-only while Picks is (routers/picks.py).
        "scoreboard": await part("scoreboard", digest.scoreboard(db.db, user.id, roles, now))
        if user.role == "admin" else None,
        "proposals_total": None if (ideas := await part("proposals_total", _ideas(user.id))) is None else len(ideas),
        "ai_activity": log,
        "autopilot": await part("autopilot", _autopilot(user.id, prefs)),
        "setup": await part("setup", _setup(user.id, prefs)),
        "backdrop": await part("backdrop", _backdrop(now)),
        "errors": errors,
    }


@router.get("/attention")
async def attention(user: User = Depends(get_current_user), broker_states=Depends(get_broker_states)):
    """The navigation badge: what needs the user except the practice engine's
    proposals (those are counted on Practice). Broker checks reuse Today's cache."""
    from backend.prefs import PrefsStore
    from backend.risk.kill_switch import KillSwitchStore

    now = datetime.now(timezone.utc)
    roles = (await PrefsStore(db.db).get(user.id)).get("broker_roles") or {}
    try:
        accounts = await _accounts(roles, user.id, broker_states)
    except Exception as exc:
        logger.warning("attention: broker states failed for %s: %s", user.id, exc)
        accounts = None
    tripped = await KillSwitchStore(db.db).is_tripped(user.id, now.astimezone(IST).date())
    kill = {"tripped": bool(tripped), "reason": (tripped or {}).get("reason")}
    return {"count": len(await _needs_you(user.id, accounts, kill, now, user.role == "admin"))}


@router.get("/reconciliation")
async def reconciliation(user: User = Depends(get_current_user), days: int = 7):
    """The user's own broker-to-ledger results, newest day first (engine/broker_recon.py). Read-only."""
    from backend.engine.broker_recon import COLLECTION

    since = (datetime.now(timezone.utc).astimezone(IST).date() - timedelta(days=max(1, min(days, 60)))).isoformat()
    rows = await db.db[COLLECTION].find({"user_id": user.id, "day": {"$gte": since}}, {"_id": 0}) \
        .sort([("day", -1), ("role", 1)]).to_list(length=None)
    for row in rows:
        row["checked_at"] = _aware(row.get("checked_at"))
    return {"results": rows}
