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

import html
import logging
import re
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


def to_html(md: str) -> str:
    """The model writes markdown; Telegram renders only a few HTML tags.
    Unclosed markers (mid-stream) stay literal until their pair arrives."""
    # ponytail: regex, not a parser; a malformed result makes Telegram 400 and
    # the caller falls back to plain text.
    parts = re.split(r"(```.*?```)", md, flags=re.S)
    out = []
    for i, part in enumerate(parts):
        if i % 2:
            code = re.sub(r"^\w*\n", "", part[3:-3])  # drop the language tag
            out.append(f"<pre>{html.escape(code.strip(), quote=False)}</pre>")
            continue
        text = html.escape(part, quote=False)
        text = re.sub(r"^#{1,6}\s+(.+)$", lambda m: f"<b>{m[1].replace('**', '')}</b>", text, flags=re.M)
        text = re.sub(r"^(\s*)[-*]\s+", r"\1• ", text, flags=re.M)
        text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
        text = re.sub(r"(?<!\w)_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)", r"<i>\1</i>", text)
        text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s\"]+)\)", r'<a href="\2">\1</a>', text)
        out.append(text)
    return "".join(out)


async def _call(method: str, body: dict, token: Optional[str]) -> Optional[dict]:
    """POST a Bot API method; the response, or None on any failure (logged)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_url(method, token), json=body)
        data = resp.json()
        if not data.get("ok"):
            # An edit with unchanged text is harmless; anything else is worth a line.
            if "not modified" not in (data.get("description") or ""):
                logger.warning("telegram %s failed: %s", method, data.get("description"))
            return None
        return data
    except Exception as exc:
        logger.warning("telegram %s failed: %s", method, exc)
        return None


async def chat_action(chat_id: int, token: Optional[str] = None) -> None:
    """Shows "typing…" in the chat for ~5 seconds."""
    await _call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, token)


async def _rich(method: str, body: dict, md: str, token: Optional[str]) -> Optional[dict]:
    """Send or edit as formatted HTML, falling back to the raw text."""
    data = await _call(method, {**body, "text": to_html(md), "parse_mode": "HTML"}, token)
    return data or await _call(method, {**body, "text": md}, token)


async def send_rich(chat_id: int, md: str, token: Optional[str] = None,
                    reply_markup: Optional[dict] = None) -> Optional[int]:
    """Send formatted markdown; the new message's id, for later edits."""
    body = {"chat_id": chat_id, **({"reply_markup": reply_markup} if reply_markup else {})}
    data = await _rich("sendMessage", body, md, token)
    return data["result"]["message_id"] if data else None


async def edit_rich(chat_id: int, message_id: int, md: str, token: Optional[str] = None,
                    reply_markup: Optional[dict] = None) -> None:
    body = {"chat_id": chat_id, "message_id": message_id, **({"reply_markup": reply_markup} if reply_markup else {})}
    await _rich("editMessageText", body, md, token)


async def alert(db, user_id: str, text: str) -> bool:
    """The one way to message a user: their own bot if they added one, else
    the server's, to the chat they linked. A no-op for an unlinked user."""
    from backend.guardrails.store import GuardrailStore

    channel = await GuardrailStore(db).telegram_channel(user_id)
    if channel is None:
        return False
    token, chat_id = channel
    return await send(chat_id, text, token)
