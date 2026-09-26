"""Telegram alerts through one deployment-wide bot (TELEGRAM_BOT_TOKEN,
created by a human with @BotFather). Linking a user needs no webhook: the
app hands out a t.me deep link carrying a one-time code, the user taps
Start, and `find_chat` reads the bot's recent updates for that code.

Bot API used (https://core.telegram.org/bots/api): getMe, getUpdates,
sendMessage -- all GET/POST on https://api.telegram.org/bot<token>/<method>.
"""

import logging
from typing import Optional

import httpx

from backend.configs.settings import settings

logger = logging.getLogger(__name__)


def configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


def _url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"


async def bot_username() -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_url("getMe"))
        resp.raise_for_status()
    return resp.json()["result"]["username"]


async def find_chat(code: str) -> Optional[int]:
    # ponytail: scans the last 100 pending updates; a busy bot needs a webhook instead
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_url("getUpdates"), params={"allowed_updates": '["message"]'})
        resp.raise_for_status()
    for update in reversed(resp.json().get("result") or []):
        message = update.get("message") or {}
        if (message.get("text") or "").strip() == f"/start {code}":
            return message["chat"]["id"]
    return None


async def send(chat_id: int, text: str) -> bool:
    """Best effort: a failed alert is logged, never raised into the monitor."""
    if not configured():
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_url("sendMessage"), json={"chat_id": chat_id, "text": text})
            resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("telegram send failed: %s", exc)
        return False
