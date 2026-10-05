"""Inbound Telegram bridge for the linked NeoTrade bot.

The settings flow remains the source of truth for ownership: this worker only
accepts messages from a chat already linked to the matching bot.  It reuses
the regular chat agent and proposal store, so Telegram cannot create a second
or less-restricted trading path.
"""

import asyncio
import hashlib
import html
import json
import logging
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.auth.broker_credentials import get_credential_store
from backend.chat import agent
from backend.chat.actions import ActionRefused, ChatActionStore, confirm
from backend.guardrails import telegram
from backend.guardrails.store import GuardrailStore
from backend.llm import use_model
from backend.prefs import PrefsStore
from backend.auth.store import UserStore
from backend.engine.session import IST
from backend.routers.settings import UsageUnavailable, fetch_usage

logger = logging.getLogger(__name__)
POLL_SECONDS = 0.5  # pause between polls; the long poll itself does the waiting
LONG_POLL_SECONDS = 25  # Telegram holds getUpdates open until a message arrives
OFFSET_PREFIX = "telegram:ai:offset:"
LOCK_PREFIX = "telegram:ai:poll-lock:"
LOCK_SECONDS = 60  # must outlast one long poll
HISTORY_PREFIX = "telegram:ai:history:"
HISTORY_TURNS = 10  # user + assistant messages kept, so "yes, do it" has context
HISTORY_SECONDS = 6 * 60 * 60
START_SECONDS = 15 * 60  # matches the Settings link code's lifetime
SUGGEST_PREFIX = "telegram:ai:suggest:"
SUGGEST_LAST_PREFIX = "telegram:ai:suggest-last:"  # message carrying the live suggestion buttons
DRAFT_SECONDS = 0.5  # how often the live draft is redrawn
DRAFT_KEEPALIVE = 10  # a draft expires after ~30s; resend it while tools are slow
TYPING_SECONDS = 4  # fallback when drafts are unavailable: "typing…" lasts ~5s
MESSAGE_LIMIT = 2800  # answer text per message; leaves room for the steps under 4096
STEPS_SHOWN = 8
CURSOR = " ▍"
# The bot's command menu (setMyCommands). Shortcuts are asked of the AI as
# these questions, so they get the same tools, steps and Confirm cards.
SHORTCUTS = {
    "portfolio": ("How is my portfolio doing?", "Portfolio summary"),
    "proposals": ("What proposals are pending for me?", "Pending proposals"),
    "engine": ("What is my paper engine doing today?", "Paper engine status"),
    "limits": ("Show my limits and guardrails.", "Limits and guardrails"),
    "journal": ("Summarise my recent journal.", "Recent journal"),
}
COMMANDS = [{"command": name, "description": label} for name, (_, label) in SHORTCUTS.items()] + [
    {"command": "new", "description": "Start a fresh conversation"},
    {"command": "usage", "description": "Gateway usage (admins)"},
    {"command": "help", "description": "What I can do"},
]
HELP = ("Ask NeoTrade anything about your account -- portfolio and its history, real and paper trades, engine runs, "
        "proposals, settings, watchlist -- or about a stock. "
        "I can prepare actions, but nothing changes until you tap Confirm.\n\n"
        + "\n".join(f"/{c['command']} — {c['description']}" for c in COMMANDS))
_menus_set: set[Optional[str]] = set()  # bots whose menu this process already replaced

# Rendered into the chat prompt's page note, so the model points at the buttons here, not the app.
TELEGRAM_CONTEXT = {"page": "Telegram chat on a phone (action cards appear right here with Confirm and Cancel "
                            "buttons; prefer short bullet lists to tables, and keep any table to 2-3 short columns)"}


def _offset_key(token: Optional[str]) -> str:
    # Redis stores a one-way identifier, never a bot token.
    identity = token or "deployment-bot"
    return OFFSET_PREFIX + hashlib.sha256(identity.encode()).hexdigest()


def _lock_key(token: Optional[str]) -> str:
    return LOCK_PREFIX + _offset_key(token).removeprefix(OFFSET_PREFIX)


def _as_text(value) -> Optional[str]:
    return value.decode() if isinstance(value, bytes) else value


async def _history(redis, user_id: str) -> list[dict]:
    if redis is None:
        return []
    raw = await redis.get(HISTORY_PREFIX + user_id)
    return json.loads(raw) if raw else []


async def _remember(redis, user_id: str, history: list[dict], question: str, answer: str) -> None:
    if redis is None:
        return
    turns = history + [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    await redis.set(HISTORY_PREFIX + user_id, json.dumps(turns[-HISTORY_TURNS:]), ex=HISTORY_SECONDS)


def _buttons(action: dict) -> list[list[dict]]:
    action_id = action["id"]
    return [[
        {"text": "Confirm", "callback_data": f"nt:confirm:{action_id}"},
        {"text": "Cancel", "callback_data": f"nt:cancel:{action_id}"},
    ]]


async def _clear_suggestions(redis, user_id: str, chat_id: int, token: Optional[str]) -> None:
    """Suggestions answer the last reply only; drop them once the user moves on."""
    if redis is None:
        return
    message_id = _as_text(await redis.get(SUGGEST_LAST_PREFIX + user_id))
    if message_id:
        await redis.delete(SUGGEST_LAST_PREFIX + user_id)
        await telegram.clear_buttons(chat_id, int(message_id), token)


def _when(iso: Optional[str], with_time: bool = False) -> str:
    """Like the sheet: "06:19" today, "07 Oct" later (IST)."""
    if not iso:
        return ""
    when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    when = (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).astimezone(IST)
    if with_time:
        return when.strftime("%d %b %H:%M")
    return when.strftime("%H:%M") if when.date() == datetime.now(IST).date() else when.strftime("%d %b")


def _bar(pct) -> str:
    if pct is None:
        return "—"
    filled = round(max(0, min(100, pct)) / 10)
    return f"{'▓' * filled}{'░' * (10 - filled)} {round(pct)}% left" + (" 🔴" if pct < 20 else "")


def _usage_html(usage: dict) -> str:
    """The Settings > AI > Usage sheet as one Telegram message."""
    esc = html.escape
    tokens, cost = usage["tokens"], usage["cost"]
    lines = [f"<b>Usage</b> · " + (f"Key {esc(usage['key_name'])}" if usage.get("key_name") else "OmniRoute"), "",
             "This month, this app's key", f"<b>{tokens['total']:,} tokens</b>",
             f"Input {tokens['input']:,} · Output {tokens['output']:,} · Reasoning {tokens['reasoning']:,}",
             f"Cost ${float(cost.get('used_usd') or 0):.2f}"
             + (f" of ${float(cost['limit_usd']):.2f}" if cost.get("limit_usd") is not None else " · no cost limit")
             + (f" · resets {_when(cost['reset_at'], with_time=True)}" if cost.get("reset_at") else ""),
             "", "<b>Providers · quota left</b>",
             "<i>The gateway's shared accounts, not only this app's use. Models in one pool share its limit.</i>"]
    for provider in usage["providers"]:
        if not provider.get("pools"):
            continue
        lines += ["", f"<b>{esc(provider['provider'] or '')}</b>" + (f" {esc(provider['plan'])}" if provider.get("plan") else "")]
        for pool in provider["pools"]:
            meta = " · ".join(filter(None, [
                f"resets {_when(pool['reset_at'])}" if pool.get("reset_at") else "",
                f"{len(pool['models'])} model{'s' if len(pool['models']) != 1 else ''}" if pool["models"] else "",
            ]))
            lines.append(f"{esc(pool['label'])}\n<code>{_bar(pool.get('remaining_pct'))}</code>" + (f"\n<i>{meta}</i>" if meta else ""))
            if pool["models"]:
                lines.append(f"<blockquote expandable>{esc(', '.join(pool['models']))}</blockquote>")
    return "\n".join(lines)


async def _usage(db, user_id: str, chat_id: int, token: Optional[str]) -> None:
    # Same gate as the Settings sheet: it is the deployment's shared gateway key.
    user = await UserStore(db).get_by_id(user_id)
    if not user or user.role != "admin":
        await telegram.send(chat_id, "Usage is for administrators.", token)
        return
    try:
        await telegram.send_html(chat_id, _usage_html(await fetch_usage()), token)
    except UsageUnavailable as exc:
        await telegram.send(chat_id, f"Usage unavailable: {exc.detail}", token)


async def _reply(db, redis, user_id: str, chat_id: int, token: Optional[str], text: str) -> None:
    await _clear_suggestions(redis, user_id, chat_id, token)
    if text.startswith("/"):
        word, _, args = text[1:].partition(" ")
        command = word.split("@")[0].lower()  # "/portfolio@MyBot" in groups
        if command in SHORTCUTS:
            text = SHORTCUTS[command][0] + (f" Focus on: {args.strip()}" if args.strip() else "")
        elif command == "usage":
            await _usage(db, user_id, chat_id, token)
            return
        elif command == "new":
            if redis is not None:
                await redis.delete(HISTORY_PREFIX + user_id)
            await telegram.send(chat_id, "Fresh start: I've forgotten our earlier messages.", token)
            return
        else:  # /help, /start, and anything unknown
            await telegram.send(chat_id, HELP, token)
            return

    history = await _history(redis, user_id)
    # `text` is the model's output since its last tool call: what it wrote
    # before calling a tool is its reasoning, what it writes last is the answer.
    state = {"steps": [], "text": ""}
    cards, sent = [], {}
    stop = asyncio.Event()
    renderer = asyncio.create_task(_render(chat_id, token, state, stop))

    async def finish(failed: bool = False) -> None:
        """Stop the live draft and send the final answer and cards, once."""
        if sent:
            return
        sent["done"] = True
        stop.set()
        await asyncio.gather(renderer, return_exceptions=True)
        answer = state["text"].strip()
        if answer and not failed:
            await _remember(redis, user_id, history, text, answer)
        if not answer and not cards:
            answer = "NeoTrade could not prepare a response. Please try again."
        if answer:
            parts, steps = _split(answer), _steps_html(state["steps"])
            for i, part in enumerate(parts):
                body = telegram.to_html(part)
                if i == 0 and steps:
                    # The work stays in the final message, collapsed.
                    body = f"<blockquote expandable>{steps}</blockquote>\n{body}"
                sent["message_id"] = await telegram.send_html(chat_id, body, token)
        for card in cards:
            await telegram.send_buttons(chat_id, card["summary"], _buttons(card), token)

    try:
        prefs = await PrefsStore(db).get(user_id)
        with use_model(prefs.get("omniroute_model")):
            async for event in agent.stream_chat(db, redis, user_id, text, history, TELEGRAM_CONTEXT):
                kind, data = event["type"], event["data"]
                if kind == "step" and data["phase"] == "start":
                    if state["text"].strip():
                        state["steps"].append({"think": state["text"].strip()})
                    state["text"] = ""
                    state["steps"].append({"id": data["id"], "label": data["label"],
                                           "input": data.get("input"), "done": False})
                elif kind == "step":
                    for step in state["steps"]:
                        if step.get("id") == data["id"]:
                            step["done"] = True
                elif kind == "content":
                    state["text"] += data
                elif kind == "action":
                    cards.append(data)
                elif kind == "answer_end":
                    await finish()  # don't make the user wait for the follow-up call
                elif kind == "suggestions" and sent.get("message_id") is not None:
                    await _attach_suggestions(redis, user_id, chat_id, token, sent["message_id"], data)
    except Exception:
        logger.exception("telegram chat failed for user %s", user_id)
        if not sent:
            state["text"] = "NeoTrade could not answer that right now. Please try again shortly."
            await finish(failed=True)
    finally:
        await finish()


PAIR_MAX_CHARS = 20  # two buttons share a row only if both labels fit half a phone's width


def _suggestion_rows(suggestions: list[str]) -> list[list[dict]]:
    """Short labels two to a row, long ones on their own -- compact, nothing cut off."""
    rows: list[list[dict]] = []
    for i, q in enumerate(suggestions):
        button = {"text": q[:64], "callback_data": f"nt:ask:{i}"}
        last = rows[-1] if rows else None
        if last and len(last) == 1 and len(q) <= PAIR_MAX_CHARS and len(last[0]["text"]) <= PAIR_MAX_CHARS:
            last.append(button)
        else:
            rows.append([button])
    return rows


async def _attach_suggestions(redis, user_id: str, chat_id: int, token: Optional[str],
                              message_id: int, suggestions: list[str]) -> None:
    """Suggested next questions arrive after the answer: add them as buttons
    under it. Tapping one asks it (see _callback); they live in Redis by message."""
    if not suggestions:
        return
    await telegram.set_buttons(chat_id, message_id, _suggestion_rows(suggestions), token)
    if redis is not None:
        await redis.set(f"{SUGGEST_PREFIX}{user_id}:{message_id}", json.dumps(suggestions), ex=HISTORY_SECONDS)
        await redis.set(SUGGEST_LAST_PREFIX + user_id, str(message_id), ex=HISTORY_SECONDS)


def _split(text: str) -> list[str]:
    parts = []
    while len(text) > MESSAGE_LIMIT:
        cut = text.rfind("\n", 0, MESSAGE_LIMIT)
        cut = cut if cut > 0 else MESSAGE_LIMIT
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    return parts + [text]


def _args(value) -> str:
    if isinstance(value, dict):
        value = ", ".join(f"{k}={v}" for k, v in value.items() if v not in (None, "", [], {}))
    return str(value or "")[:60]


def _steps_html(steps: list[dict]) -> str:
    lines = []
    for step in steps[-STEPS_SHOWN:]:
        if "think" in step:
            thought = step["think"]
            lines.append(f"💭 <i>{telegram.to_html(thought[:150] + ('…' if len(thought) > 150 else ''))}</i>")
        else:
            args = _args(step["input"])
            lines.append(f"{'✅' if step['done'] else '⏳'} {html.escape(step['label'])}"
                         + (f" <code>{html.escape(args)}</code>" if args else ""))
    return "\n".join(lines)


def _draft_html(state: dict) -> str:
    text = state["text"].strip()[-MESSAGE_LIMIT:]
    body = telegram.to_html(text) + CURSOR if text else ""
    # Before the first words or tool step, say so instead of an empty bubble.
    return "\n\n".join(p for p in (_steps_html(state["steps"]), body) if p) or "💭 <i>Thinking…</i>"


async def _render(chat_id: int, token: Optional[str], state: dict, stop: asyncio.Event) -> None:
    """Redraw the live draft from `state` until `stop`; Telegram animates the
    changes. Drafts work only in private chats (positive ids), and some
    Telegram apps accept but do not show them, so "typing…" is always sent too."""
    draft_id = random.randint(1, 2**31 - 1)
    drafts = chat_id > 0
    shown, shown_at, typed_at = None, 0.0, 0.0
    while not stop.is_set():
        now = time.monotonic()
        if now - typed_at > TYPING_SECONDS:
            await telegram.chat_action(chat_id, token)
            typed_at = now
        if drafts:
            current = _draft_html(state)
            if current != shown or now - shown_at > DRAFT_KEEPALIVE:
                drafts = await telegram.draft(chat_id, draft_id, current, token)
                shown, shown_at = current, now
        try:
            await asyncio.wait_for(stop.wait(), DRAFT_SECONDS)
        except asyncio.TimeoutError:
            pass


async def _callback(db, redis, user_id: str, chat_id: int, token: Optional[str], callback: dict) -> None:
    data = callback.get("data") or ""
    callback_id = callback.get("id", "")
    _, _, action_id = data.partition("nt:")
    command, _, action_id = action_id.partition(":")
    if command == "ask":
        await _ask(db, redis, user_id, chat_id, token, callback, action_id)
        return
    if command == "autopilot" and action_id == "off":
        from backend.autopilot.service import disable

        stopped = await disable(db, user_id)
        text = "🛑 Autopilot stopped." if stopped else "Autopilot is already off."
        await telegram.answer_callback(callback_id, text, token)
        card = callback.get("message") or {}
        if stopped and card.get("message_id"):
            await telegram.edit_html(chat_id, card["message_id"],
                                     f"{html.escape(card.get('text') or '', quote=False)}\n\n{text}", token)
        return
    if command not in {"confirm", "confirm2", "cancel"} or not action_id:
        return
    done = False
    card = callback.get("message") or {}
    try:
        if command == "cancel":
            changed = await ChatActionStore(db).cancel(user_id, action_id)
            result = "Cancelled." if changed else "That action can no longer be cancelled."
        else:
            outcome = await confirm(db, redis, get_credential_store(), user_id, action_id,
                                    second_tap=command == "confirm2")
            result = outcome["result"]
            if outcome["status"] == "NEEDS_SECOND_TAP" and card.get("message_id"):
                # Real money: the card re-arms with a Send button; that tap is the second.
                await telegram.answer_callback(callback_id, result[:180], token)
                await telegram.edit_html(
                    chat_id, card["message_id"],
                    f"{html.escape(card.get('text') or '', quote=False)}\n\n⚠️ Real money. Tap Send real order to place it.",
                    token, reply_markup={"inline_keyboard": [[
                        {"text": "Send real order", "callback_data": f"nt:confirm2:{action_id}"},
                        {"text": "Cancel", "callback_data": f"nt:cancel:{action_id}"},
                    ]]})
                return
            done = True
    except ActionRefused as exc:
        result = str(exc)
    except Exception:
        logger.exception("telegram action failed for user %s", user_id)
        result = "NeoTrade could not complete that action. Please check the app and try again."
    await telegram.answer_callback(callback_id, result[:180], token)
    if card.get("message_id"):
        # The card shows its outcome and loses its buttons -- no extra message.
        await telegram.edit_html(chat_id, card["message_id"],
                                 f"{html.escape(card.get('text') or '', quote=False)}\n\n{'✅' if done else '✖'} "
                                 f"{html.escape(result, quote=False)}", token)
    else:
        await telegram.send(chat_id, result, token)


async def _ask(db, redis, user_id: str, chat_id: int, token: Optional[str], callback: dict, index: str) -> None:
    """A tapped suggestion: echo it, then answer it like a typed message."""
    began = time.monotonic()
    message_id = (callback.get("message") or {}).get("message_id")
    raw = await redis.get(f"{SUGGEST_PREFIX}{user_id}:{message_id}") if redis is not None else None
    questions = json.loads(raw) if raw else []
    question = questions[int(index)] if index.isdigit() and int(index) < len(questions) else None
    await telegram.answer_callback(callback.get("id", ""), "" if question else "That suggestion expired.", token)
    logger.info("telegram suggestion tap acknowledged in %.2fs", time.monotonic() - began)
    if question:
        await telegram.send_rich(chat_id, f"» _{question}_", token)
        await _reply(db, redis, user_id, chat_id, token, question)


async def poll_once(db, redis) -> int:
    """Long-poll every linked bot once, concurrently, so a quiet bot never
    delays another. Returns how many updates were handled."""
    routes = await GuardrailStore(db).telegram_routes()
    return sum(await asyncio.gather(*(_poll_bot(db, redis, token, chats) for token, chats in routes)))


async def _poll_bot(db, redis, token: Optional[str], chats: dict) -> int:
    handled = 0
    key = _offset_key(token)
    lock_key, lock_owner = _lock_key(token), str(uuid.uuid4())
    if token not in _menus_set:
        # Replace whatever menu the bot had (e.g. another app's) with ours.
        if await telegram.set_commands(COMMANDS, token):
            _menus_set.add(token)
    if redis is not None:
        # One worker per bot: concurrent getUpdates calls get 409 Conflict.
        acquired = await redis.set(lock_key, lock_owner, nx=True, ex=LOCK_SECONDS)
        if not acquired:
            return 0
    try:
        raw_offset = await redis.get(key) if redis is not None else None
        offset = int(raw_offset) if raw_offset is not None else None
        try:
            updates = await telegram.updates(offset, token, LONG_POLL_SECONDS)
        except Exception:
            logger.exception("telegram polling failed")
            return 0
        for update in updates:
            sent_at = ((update.get("message") or {}).get("date"))
            logger.info("telegram update %s: %s%s", update.get("update_id"),
                        "message" if update.get("message") else "callback" if update.get("callback_query") else "other",
                        f", {time.time() - sent_at:.1f}s after it was sent" if sent_at else "")
        # Commit the whole batch before the slow AI replies: if the lock
        # expires mid-batch, another worker must not fetch it again.
        ids = [u["update_id"] for u in updates if u.get("update_id") is not None]
        if ids and redis is not None:
            await redis.set(key, str(max(ids) + 1))
        for update in updates:
            message = update.get("message")
            callback = update.get("callback_query")
            chat_id = (message or {}).get("chat", {}).get("id") or (callback or {}).get("message", {}).get("chat", {}).get("id")
            text = (message or {}).get("text") or ""
            if text.startswith("/start ") and redis is not None:
                # Consumed updates are gone from getUpdates; keep the
                # Settings link flow working for a (re)linked chat.
                await redis.set(telegram.start_key(text[7:].strip()), str(chat_id), ex=START_SECONDS)
            user_id = chats.get(chat_id)
            if user_id is None:
                continue
            handled += 1
            if message:
                await _reply(db, redis, user_id, chat_id, token, text)
            elif callback:
                await _callback(db, redis, user_id, chat_id, token, callback)
    finally:
        # Do not delete another worker's lock if ours expired mid-request.
        if redis is not None and _as_text(await redis.get(lock_key)) == lock_owner:
            await redis.delete(lock_key)
    return handled


async def poll_loop(db, redis) -> None:
    while True:
        try:
            await poll_once(db, redis)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("telegram polling loop failed")
        await asyncio.sleep(POLL_SECONDS)


def start(db, redis) -> asyncio.Task:
    return asyncio.create_task(poll_loop(db, redis))
