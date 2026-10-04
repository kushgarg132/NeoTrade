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
from typing import Optional

from backend.auth.broker_credentials import get_credential_store
from backend.chat import agent
from backend.chat.actions import ActionRefused, ChatActionStore, confirm
from backend.guardrails import telegram
from backend.guardrails.store import GuardrailStore
from backend.llm import use_model
from backend.prefs import PrefsStore

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
DRAFT_SECONDS = 0.5  # how often the live draft is redrawn
DRAFT_KEEPALIVE = 10  # a draft expires after ~30s; resend it while tools are slow
TYPING_SECONDS = 4  # fallback when drafts are unavailable: "typing…" lasts ~5s
MESSAGE_LIMIT = 2800  # answer text per message; leaves room for the steps under 4096
STEPS_SHOWN = 8
CURSOR = " ▍"
# Rendered into the chat prompt's page note, so the model points at the buttons here, not the app.
TELEGRAM_CONTEXT = {"page": "Telegram chat (action cards appear right here with Confirm and Cancel buttons)"}


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


async def _reply(db, redis, user_id: str, chat_id: int, token: Optional[str], text: str) -> None:
    if text.strip() == "/help" or text.startswith("/start"):
        await telegram.send(chat_id, "Ask NeoTrade about your portfolio, journal, proposals, paper engine, or limits. "
                            "I can prepare actions, but nothing changes until you tap Confirm.", token)
        return
    if text.startswith("/"):
        await telegram.send(chat_id, "Use /help or send a question for your NeoTrade assistant.", token)
        return

    history = await _history(redis, user_id)
    # `text` is the model's output since its last tool call: what it wrote
    # before calling a tool is its reasoning, what it writes last is the answer.
    state = {"steps": [], "text": ""}
    cards, suggestions, failed = [], [], False
    stop = asyncio.Event()
    renderer = asyncio.create_task(_render(chat_id, token, state, stop))
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
                elif kind == "suggestions":
                    suggestions = data
    except Exception:
        logger.exception("telegram chat failed for user %s", user_id)
        failed = True
        state["text"] = "NeoTrade could not answer that right now. Please try again shortly."
    finally:
        stop.set()
        await asyncio.gather(renderer, return_exceptions=True)

    answer = state["text"].strip()
    if answer and not failed:
        await _remember(redis, user_id, history, text, answer)
    if not answer and not cards:
        answer = "NeoTrade could not prepare a response. Please try again."
    if answer:
        # Suggested next questions: buttons under the final answer. Tapping one
        # asks it (see _callback); the questions live in Redis by message.
        markup = {"inline_keyboard": [[{"text": q[:64], "callback_data": f"nt:ask:{i}"}]
                                      for i, q in enumerate(suggestions)]} if suggestions else None
        parts, steps, message_id = _split(answer), _steps_html(state["steps"]), None
        for i, part in enumerate(parts):
            body = telegram.to_html(part)
            if i == 0 and steps:
                # The work stays in the final message, collapsed.
                body = f"<blockquote expandable>{steps}</blockquote>\n{body}"
            message_id = await telegram.send_html(chat_id, body, token, markup if i == len(parts) - 1 else None)
        if suggestions and message_id is not None and redis is not None:
            await redis.set(f"{SUGGEST_PREFIX}{user_id}:{message_id}", json.dumps(suggestions), ex=HISTORY_SECONDS)
    for card in cards:
        await telegram.send_buttons(chat_id, card["summary"], _buttons(card), token)


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
    return "\n\n".join(p for p in (_steps_html(state["steps"]), body) if p)


async def _render(chat_id: int, token: Optional[str], state: dict, stop: asyncio.Event) -> None:
    """Redraw the live draft from `state` until `stop`; Telegram animates the
    changes. Drafts work only in private chats (positive ids); otherwise, or if
    the API refuses, fall back to the "typing…" status."""
    draft_id = random.randint(1, 2**31 - 1)
    drafts = chat_id > 0
    shown, shown_at = None, 0.0
    while not stop.is_set():
        now = time.monotonic()
        if drafts:
            current = _draft_html(state)
            if current != shown or now - shown_at > DRAFT_KEEPALIVE:
                drafts = await telegram.draft(chat_id, draft_id, current, token)
                shown, shown_at = current, now
        elif now - shown_at > TYPING_SECONDS:
            await telegram.chat_action(chat_id, token)
            shown_at = now
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
    if command not in {"confirm", "cancel"} or not action_id:
        return
    try:
        if command == "cancel":
            changed = await ChatActionStore(db).cancel(user_id, action_id)
            result = "Cancelled." if changed else "That action can no longer be cancelled."
        else:
            result = (await confirm(db, redis, get_credential_store(), user_id, action_id))["result"]
    except ActionRefused as exc:
        result = str(exc)
    except Exception:
        logger.exception("telegram action failed for user %s", user_id)
        result = "NeoTrade could not complete that action. Please check the app and try again."
    await telegram.answer_callback(callback_id, result[:180], token)
    await telegram.send(chat_id, result, token)


async def _ask(db, redis, user_id: str, chat_id: int, token: Optional[str], callback: dict, index: str) -> None:
    """A tapped suggestion: echo it, then answer it like a typed message."""
    message_id = (callback.get("message") or {}).get("message_id")
    raw = await redis.get(f"{SUGGEST_PREFIX}{user_id}:{message_id}") if redis is not None else None
    questions = json.loads(raw) if raw else []
    question = questions[int(index)] if index.isdigit() and int(index) < len(questions) else None
    await telegram.answer_callback(callback.get("id", ""), "" if question else "That suggestion expired.", token)
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
