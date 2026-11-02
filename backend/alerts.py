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
CLIP = 120
DIGEST_MAX = 2500


def _clip(text: str) -> str:
    text = str(text)
    return text if len(text) <= CLIP else text[:CLIP - 1] + "…"


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
    try:
        if kind in ADMIN_ONLY and not await is_admin(db, user_id):
            return False
        muted = (await PrefsStore(db).get(user_id))["alert_mute"].get(kind)
    except Exception:
        logger.warning("alert prefs lookup failed", exc_info=True)
        if kind in BATCHED:
            return False
        muted = False  # an instant alert (exit, money) still goes out
    if muted:  # handled on purpose: True, so callers do not retry it
        await _log(db, user_id, kind, title, lines, symbol, link, "muted")
        return True
    if kind in BATCHED:
        await _log(db, user_id, kind, title, lines, symbol, link, "queued")
        return True
    try:
        from backend.guardrails.store import GuardrailStore

        if await GuardrailStore(db).telegram_channel(user_id) is None:
            return True  # nowhere to send: not a failure, nothing to retry
    except Exception:
        logger.warning("alert channel lookup failed", exc_info=True)
    try:
        ok = bool(await telegram.alert(db, user_id, card(kind, title, lines), html=True, buttons=buttons))
    except Exception:
        logger.warning("alert send failed", exc_info=True)
        ok = False
    await _log(db, user_id, kind, title, lines, symbol, link, "sent" if ok else "failed")
    return ok


async def _stale_line(db, user_id, until, before) -> str:
    """"N pending, M expire before close": the long-term ideas waiting on the user. Admins only."""
    from backend.risk.paper_gate import for_mine

    rows = await db["suggestions"].find({"user_id": user_id, "status": "PENDING", "mode": "LONGTERM"}).to_list(None)
    rows = await for_mine(db, user_id, rows)  # the same ideas the user sees
    if not rows:
        return ""
    n = len(rows)
    if until is None:
        return f"{n} pending"
    m = sum(1 for r in rows if r.get("expires_at") and r["expires_at"].replace(tzinfo=r["expires_at"].tzinfo or timezone.utc) < until)
    return f"{n} pending, {m} expire before {before}"


async def drain(db, user_id, now: datetime, until: datetime | None = None, before: str = "close") -> tuple[str, list]:
    """Claim this user's queued, unmuted alerts and render them as one digest block, plus the
    "Expiring ideas" line (admins, unless muted). `until`: the next digest's time, `before`: how to say it."""
    muted = (await PrefsStore(db).get(user_id))["alert_mute"]
    stale = "" if muted.get("stale_ideas") or not await is_admin(db, user_id) else await _stale_line(db, user_id, until, before)
    rows = await db["alerts"].find({"user_id": user_id, "state": "queued"}).sort("created_at", 1).to_list(None)
    ids = [r["_id"] for r in rows if not muted.get(r["kind"])]
    claimed = []
    if ids:
        claim = uuid.uuid4().hex
        await db["alerts"].update_many({"_id": {"$in": ids}, "state": "queued"},
                                       {"$set": {"state": "digested", "digested_at": now, "claim": claim}})
        # another drain may have won some rows: keep only the ones this call claimed
        claimed = await db["alerts"].find({"user_id": user_id, "state": "digested", "claim": claim}).to_list(None)
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
        for r in items[:PER_KIND]:
            out.append(f"• {html.escape(_clip(r['title']))}")
            out += [f"   {html.escape(_clip(x))}" for x in (r.get("lines") or [])[:3]]
        if len(items) > PER_KIND:
            out.append(f"…and {len(items) - PER_KIND} more")
    text = "\n".join(out)
    if len(text) > DIGEST_MAX:  # Telegram caps a message at 4096 and send_html does not split
        text = text[:DIGEST_MAX].rsplit("\n", 1)[0] + "\n…and more in the app"
    return text, [r["_id"] for r in claimed]


async def requeue(db, ids: list) -> None:
    await db["alerts"].update_many({"_id": {"$in": ids}}, {"$set": {"state": "queued", "digested_at": None}, "$unset": {"claim": ""}})
