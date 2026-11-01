"""The one way a Telegram alert leaves NeoTrade. Instant kinds send a short
card at once; batched kinds queue and ride the next digest (`drain`). Every
alert is logged in `alerts` (TTL 30 days). Best effort: nothing here raises
into the caller."""

import html
import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from backend.configs.settings import settings
from backend.engine.session import IST
from backend.guardrails import telegram
from backend.prefs import PrefsStore
from backend.suggestions.notify import is_admin

logger = logging.getLogger(__name__)

INSTANT = frozenset({"exit", "money", "news_breaking", "action"})
BATCHED = frozenset({"ideas", "news", "learning", "review", "autopilot_refused", "stale_ideas"})
KINDS = INSTANT | BATCHED
ICONS = {"exit": "🔴", "money": "🤖", "news_breaking": "📰", "action": "⚠️"}
ORDER = ("ideas", "stale_ideas", "news", "learning", "review", "autopilot_refused")
LABELS = {"ideas": "Ideas", "stale_ideas": "Expiring ideas", "news": "News", "learning": "Learning",
          "review": "Your week", "autopilot_refused": "Autopilot"}
ADMIN_ONLY = frozenset({"ideas", "stale_ideas"})
PER_KIND = 5


def split(text: str) -> tuple[str, list[str]]:
    rows = [r for r in text.splitlines() if r.strip()]
    return (rows[0], rows[1:]) if rows else ("", [])


def card(kind: str, title: str, lines: Sequence[str]) -> str:
    body = [f"{ICONS[kind]} <b>{html.escape(title)}</b>"] + [html.escape(x) for x in list(lines)[:3]]
    return "\n".join(body)


def open_button(path: str, text: str = "Open") -> list[dict]:
    return [{"text": text, "url": settings.APP_URL + path}] if settings.APP_URL else []


def sell_buttons(symbol: str, quantity: int, path: str) -> list[list[dict]]:
    from backend.guardrails.telegram_bot import Tap

    sell = {"text": f"Sell ×{quantity}", "callback_data": Tap(command="sell", id=f"{symbol}|{quantity}").pack()}
    return [[sell, *open_button(path)]]


async def _log(db, user_id, kind, title, lines, symbol, link, state, now=None) -> None:
    try:
        await db["alerts"].insert_one({
            "user_id": user_id, "kind": kind, "title": title, "lines": list(lines), "symbol": symbol,
            "link": link, "state": state, "created_at": now or datetime.now(timezone.utc), "digested_at": None,
        })
    except Exception:
        logger.warning("alert log write failed", exc_info=True)


async def alert(db, user_id, kind, title, lines=(), *, symbol=None, link=None, buttons=None) -> bool:
    if kind not in KINDS:
        raise ValueError(f"unknown alert kind {kind!r}")
    if kind in ADMIN_ONLY and not await is_admin(db, user_id):
        return False
    if (await PrefsStore(db).get(user_id))["alert_mute"].get(kind):
        await _log(db, user_id, kind, title, lines, symbol, link, "muted")
        return False
    if kind in BATCHED:
        await _log(db, user_id, kind, title, lines, symbol, link, "queued")
        return True
    try:
        ok = bool(await telegram.alert(db, user_id, card(kind, title, lines), html=True, buttons=buttons))
    except Exception:
        logger.warning("alert send failed", exc_info=True)
        ok = False
    await _log(db, user_id, kind, title, lines, symbol, link, "sent" if ok else "failed")
    return ok


async def _stale_line(db, user_id, until) -> str:
    """"N pending, M expire before close": the long-term ideas waiting on the user. Admins only."""
    query = {"user_id": user_id, "status": "PENDING", "mode": "LONGTERM"}
    n = await db["suggestions"].count_documents(query)
    if not n:
        return ""
    if until is None:
        return f"{n} pending"
    m = await db["suggestions"].count_documents({**query, "expires_at": {"$lt": until}})
    return f"{n} pending, {m} expire before {'close' if until.astimezone(IST).hour == 15 else 'the open'}"


async def drain(db, user_id, now: datetime, until: datetime | None = None) -> tuple[str, list]:
    """Claim this user's queued, unmuted alerts and render them as one digest block, plus the
    "Expiring ideas" line (admins, unless muted). `until`: the next digest's time."""
    muted = (await PrefsStore(db).get(user_id))["alert_mute"]
    stale = "" if muted.get("stale_ideas") or not await is_admin(db, user_id) else await _stale_line(db, user_id, until)
    rows = await db["alerts"].find({"user_id": user_id, "state": "queued"}).sort("created_at", 1).to_list(None)
    ids = [r["_id"] for r in rows if not muted.get(r["kind"])]
    claimed = []
    if ids:
        claim = uuid.uuid4().hex
        await db["alerts"].update_many({"_id": {"$in": ids}, "state": "queued"},
                                       {"$set": {"state": "digested", "digested_at": now, "claim": claim}})
        # another drain may have won some rows: keep only the ones this call claimed
        claimed = await db["alerts"].find({"claim": claim}).to_list(None)
    if not claimed and not stale:
        return "", []
    out = ["<b>Since last update</b>"]
    for kind in ORDER:
        items = [r for r in claimed if r["kind"] == kind]
        if kind == "stale_ideas" and stale:
            out += [f"<b>{LABELS[kind]}</b>", f"• {stale}"]
            continue
        if not items:
            continue
        out.append(f"<b>{LABELS[kind]}</b>")
        out += [f"• {html.escape(r['title'])}" for r in items[:PER_KIND]]
        if len(items) > PER_KIND:
            out.append(f"…and {len(items) - PER_KIND} more")
    return "\n".join(out), [r["_id"] for r in claimed]


async def requeue(db, ids: list) -> None:
    await db["alerts"].update_many({"_id": {"$in": ids}}, {"$set": {"state": "queued", "digested_at": None}, "$unset": {"claim": ""}})
