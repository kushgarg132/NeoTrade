"""Inbound Telegram bridge for the linked NeoTrade bot.

The settings flow remains the source of truth for ownership: this worker only
accepts messages from a chat already linked to the matching bot.  It reuses
the regular chat agent and proposal store, so Telegram cannot create a second
or less-restricted trading path.
"""

import asyncio
import hashlib
import logging
from typing import Optional

from backend.auth.broker_credentials import get_credential_store
from backend.chat import agent
from backend.chat.actions import ActionRefused, ChatActionStore, confirm
from backend.guardrails import telegram
from backend.guardrails.store import GuardrailStore

logger = logging.getLogger(__name__)
POLL_SECONDS = 3
OFFSET_PREFIX = "telegram:ai:offset:"


def _offset_key(token: Optional[str]) -> str:
    # Redis stores a one-way identifier, never a bot token.
    identity = token or "deployment-bot"
    return OFFSET_PREFIX + hashlib.sha256(identity.encode()).hexdigest()


def _buttons(action: dict) -> list[list[dict]]:
    action_id = action["id"]
    return [[
        {"text": "Confirm", "callback_data": f"nt:confirm:{action_id}"},
        {"text": "Cancel", "callback_data": f"nt:cancel:{action_id}"},
    ]]


async def _reply(db, redis, user_id: str, chat_id: int, token: Optional[str], text: str) -> None:
    if text.strip() == "/help":
        await telegram.send(chat_id, "Ask NeoTrade about your portfolio, journal, proposals, paper engine, or limits. "
                            "I can prepare actions, but nothing changes until you tap Confirm.", token)
        return
    if text.startswith("/"):
        await telegram.send(chat_id, "Use /help or send a question for your NeoTrade assistant.", token)
        return

    chunks, cards = [], []
    try:
        async for event in agent.stream_chat(db, redis, user_id, text, [], {"page": "telegram"}):
            if event["type"] == "content":
                chunks.append(event["data"])
            elif event["type"] == "action":
                cards.append(event["data"])
    except Exception:
        logger.exception("telegram chat failed for user %s", user_id)
        await telegram.send(chat_id, "NeoTrade could not answer that right now. Please try again shortly.", token)
        return

    answer = "".join(chunks).strip()
    if answer:
        # Telegram's message limit is 4096 Unicode characters.
        for start in range(0, len(answer), 4000):
            await telegram.send(chat_id, answer[start:start + 4000], token)
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
        raw_offset = await redis.get(key) if redis is not None else None
        offset = int(raw_offset) if raw_offset is not None else None
        try:
            updates = await telegram.updates(offset, token)
        except Exception:
            logger.exception("telegram polling failed")
            continue
        for update in updates:
            update_id = update.get("update_id")
            if update_id is not None and redis is not None:
                await redis.set(key, str(update_id + 1))
            message = update.get("message")
            callback = update.get("callback_query")
            chat_id = (message or {}).get("chat", {}).get("id") or (callback or {}).get("message", {}).get("chat", {}).get("id")
            user_id = chats.get(chat_id)
            if user_id is None:
                continue
            handled += 1
            if message:
                await _reply(db, redis, user_id, chat_id, token, message.get("text") or "")
            elif callback:
                await _callback(db, redis, user_id, chat_id, token, callback)
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
