"""Inbound Telegram bridge for the linked NeoTrade bot.

The settings flow remains the source of truth for ownership: this worker only
accepts messages from a chat already linked to the matching bot.  It reuses
the regular chat agent and proposal store, so Telegram cannot create a second
or less-restricted trading path.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from typing import Optional

from backend.auth.broker_credentials import get_credential_store
from backend.chat import agent
from backend.chat.actions import ActionRefused, ChatActionStore, confirm
from backend.guardrails import telegram
from backend.guardrails.store import GuardrailStore

logger = logging.getLogger(__name__)
POLL_SECONDS = 3
OFFSET_PREFIX = "telegram:ai:offset:"
LOCK_PREFIX = "telegram:ai:poll-lock:"
LOCK_SECONDS = 30
HISTORY_PREFIX = "telegram:ai:history:"
HISTORY_TURNS = 10  # user + assistant messages kept, so "yes, do it" has context
HISTORY_SECONDS = 6 * 60 * 60
START_SECONDS = 15 * 60  # matches the Settings link code's lifetime


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

    chunks, cards, suggestions = [], [], []
    history = await _history(redis, user_id)
    try:
        async for event in agent.stream_chat(db, redis, user_id, text, history, {"page": "telegram"}):
            if event["type"] == "content":
                chunks.append(event["data"])
            elif event["type"] == "action":
                cards.append(event["data"])
            elif event["type"] == "suggestions":
                suggestions = event["data"]
    except Exception:
        logger.exception("telegram chat failed for user %s", user_id)
        await telegram.send(chat_id, "NeoTrade could not answer that right now. Please try again shortly.", token)
        return

    answer = "".join(chunks).strip()
    if answer:
        await _remember(redis, user_id, history, text, answer)
    if answer:
        # Suggested next questions ride on the last chunk as a reply keyboard:
        # tapping one sends it back as the user's next message.
        keyboard = {"keyboard": [[{"text": q}] for q in suggestions],
                    "one_time_keyboard": True, "resize_keyboard": True} if suggestions else None
        # Telegram's message limit is 4096 Unicode characters.
        starts = range(0, len(answer), 4000)
        for start in starts:
            await telegram.send(chat_id, answer[start:start + 4000], token,
                                keyboard if start == starts[-1] else None)
    elif not cards:
        await telegram.send(chat_id, "NeoTrade could not prepare a response. Please try again.", token)
    for card in cards:
        await telegram.send_buttons(chat_id, card["summary"], _buttons(card), token)


async def _callback(db, redis, user_id: str, chat_id: int, token: Optional[str], callback: dict) -> None:
    data = callback.get("data") or ""
    callback_id = callback.get("id", "")
    _, _, action_id = data.partition("nt:")
    command, _, action_id = action_id.partition(":")
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


async def poll_once(db, redis) -> int:
    """Process pending updates for every linked bot once. Returns update count."""
    handled = 0
    for token, chats in await GuardrailStore(db).telegram_routes():
        key = _offset_key(token)
        lock_key, lock_owner = _lock_key(token), str(uuid.uuid4())
        if redis is not None:
            acquired = await redis.set(lock_key, lock_owner, nx=True, ex=LOCK_SECONDS)
            if not acquired:
                continue
        try:
            raw_offset = await redis.get(key) if redis is not None else None
            offset = int(raw_offset) if raw_offset is not None else None
            try:
                updates = await telegram.updates(offset, token)
            except Exception:
                logger.exception("telegram polling failed")
                continue
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
