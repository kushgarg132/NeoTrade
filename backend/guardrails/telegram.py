"""Telegram alerts. Each user may bring their own bot (a token from
@BotFather, stored encrypted by GuardrailStore); otherwise the
deployment-wide bot (TELEGRAM_BOT_TOKEN) is used, if this server has one.
Linking a user needs no webhook: the app hands out a t.me deep link carrying
a one-time code, the user taps Start, and `find_chat` reads that bot's
recent updates for the code. Every function takes the bot `token`; None
means the deployment-wide bot.

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


def _url(method: str, token: Optional[str] = None) -> str:
    return f"https://api.telegram.org/bot{token or settings.TELEGRAM_BOT_TOKEN}/{method}"


async def bot_username(token: Optional[str] = None) -> str:
    """Also how a pasted token is validated: Telegram rejects a bad one."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_url("getMe", token))
        resp.raise_for_status()
    return resp.json()["result"]["username"]


def start_key(code: str) -> str:
    return f"telegram:start:{code}"


async def find_chat(code: str, token: Optional[str] = None) -> Optional[int]:
    # ponytail: scans the last 100 pending updates; a busy bot needs a webhook instead
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_url("getUpdates", token), params={"allowed_updates": '["message"]'})
        resp.raise_for_status()
    for update in reversed(resp.json().get("result") or []):
        message = update.get("message") or {}
        if (message.get("text") or "").strip() == f"/start {code}":
            return message["chat"]["id"]
    return None


async def updates(offset: Optional[int] = None, token: Optional[str] = None) -> list[dict]:
    """Read a bot's pending updates without logging its token.

    Long polling is deliberately used instead of a public webhook: a user can
    bring their own BotFather bot, whose webhook configuration NeoTrade does
    not own.  Callers persist the next offset after handling each batch.
    """
    params = {"allowed_updates": '["message","callback_query"]'}
    if offset is not None:
        params["offset"] = offset
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(_url("getUpdates", token), params=params)
        resp.raise_for_status()
    return resp.json().get("result") or []


async def send(chat_id: int, text: str, token: Optional[str] = None, reply_markup: Optional[dict] = None) -> bool:
    """Best effort: a failed alert is logged, never raised into the monitor."""
    if not (token or configured()):
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            body = {"chat_id": chat_id, "text": text}
            if reply_markup:
                body["reply_markup"] = reply_markup
            resp = await client.post(_url("sendMessage", token), json=body)
            resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("telegram send failed: %s", exc)
        return False


async def send_buttons(chat_id: int, text: str, buttons: list[list[dict]], token: Optional[str] = None) -> bool:
    """Send a proposal card. Callback data carries only an opaque action id."""
    if not (token or configured()):
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_url("sendMessage", token), json={
                "chat_id": chat_id, "text": text,
                "reply_markup": {"inline_keyboard": buttons},
            })
            resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("telegram button send failed: %s", exc)
        return False


async def answer_callback(callback_id: str, text: str, token: Optional[str] = None) -> None:
    """Dismiss Telegram's button spinner; errors are non-fatal."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(_url("answerCallbackQuery", token), json={"callback_query_id": callback_id, "text": text})
    except Exception as exc:
        logger.warning("telegram callback acknowledgement failed: %s", exc)


async def alert(db, user_id: str, text: str) -> bool:
    """The one way to message a user: their own bot if they added one, else
    the server's, to the chat they linked. A no-op for an unlinked user."""
    from backend.guardrails.store import GuardrailStore

    channel = await GuardrailStore(db).telegram_channel(user_id)
    if channel is None:
        return False
    token, chat_id = channel
    return await send(chat_id, text, token)
