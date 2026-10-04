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

import asyncio
import html
import logging
import weakref
import re
from typing import Optional

import httpx

from backend.configs.settings import settings

logger = logging.getLogger(__name__)


def configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


_CLIENTS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()  # event loop -> client


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=60))


class _http:
    """`async with _http(timeout=...) as client`: borrows this worker's shared
    keep-alive client instead of opening a new HTTPS connection per call
    (each new one cost ~0.5s: taps, drafts and edits all felt it). The
    client is never closed here; one per event loop."""

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    async def __aenter__(self):
        loop = asyncio.get_running_loop()
        client = _CLIENTS.get(loop)
        if client is None or client.is_closed:
            client = _CLIENTS[loop] = _new_client()
        self.client = client
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, url, **kwargs):
        return await self.client.get(url, timeout=self.timeout, **kwargs)

    async def post(self, url, **kwargs):
        return await self.client.post(url, timeout=self.timeout, **kwargs)


def _url(method: str, token: Optional[str] = None) -> str:
    return f"https://api.telegram.org/bot{token or settings.TELEGRAM_BOT_TOKEN}/{method}"


async def bot_username(token: Optional[str] = None) -> str:
    """Also how a pasted token is validated: Telegram rejects a bad one."""
    async with _http(timeout=10.0) as client:
        resp = await client.get(_url("getMe", token))
        resp.raise_for_status()
    return resp.json()["result"]["username"]


def start_key(code: str) -> str:
    return f"telegram:start:{code}"


async def find_chat(code: str, token: Optional[str] = None) -> Optional[int]:
    # ponytail: scans the last 100 pending updates; a busy bot needs a webhook instead
    async with _http(timeout=10.0) as client:
        resp = await client.get(_url("getUpdates", token), params={"allowed_updates": '["message"]'})
    if resp.status_code == 409:
        return None  # the AI poller holds this bot; it stashes Start codes instead
    resp.raise_for_status()
    for update in reversed(resp.json().get("result") or []):
        message = update.get("message") or {}
        if (message.get("text") or "").strip() == f"/start {code}":
            return message["chat"]["id"]
    return None


async def updates(offset: Optional[int] = None, token: Optional[str] = None, wait: int = 0) -> list[dict]:
    """Read a bot's pending updates without logging its token.

    Long polling is deliberately used instead of a public webhook: a user can
    bring their own BotFather bot, whose webhook configuration NeoTrade does
    not own.  Callers persist the next offset after handling each batch.
    """
    params = {"allowed_updates": '["message","callback_query"]', "timeout": wait}
    if offset is not None:
        params["offset"] = offset
    # `wait` > 0 is a long poll: Telegram answers as soon as an update arrives.
    async with _http(timeout=wait + 10.0) as client:
        resp = await client.get(_url("getUpdates", token), params=params)
        resp.raise_for_status()
    return resp.json().get("result") or []


async def send(chat_id: int, text: str, token: Optional[str] = None, reply_markup: Optional[dict] = None) -> bool:
    """Best effort: a failed alert is logged, never raised into the monitor."""
    if not (token or configured()):
        return False
    try:
        async with _http(timeout=10.0) as client:
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
        async with _http(timeout=10.0) as client:
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
        async with _http(timeout=10.0) as client:
            await client.post(_url("answerCallbackQuery", token), json={"callback_query_id": callback_id, "text": text})
    except Exception as exc:
        logger.warning("telegram callback acknowledgement failed: %s", exc)


PRE_MAX_WIDTH = 34  # characters a phone shows on one monospace line
_TABLE = re.compile(r"(?:^[ \t]*\|.*\|[ \t]*(?:\n|$))+", re.M)
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _inline(text: str) -> str:
    """Inline markdown on already-escaped text."""
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)", r"<i>\1</i>", text)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s\"]+)\)", r'<a href="\2">\1</a>', text)


def _table(block: str) -> Optional[str]:
    """Telegram has no tables. A narrow one becomes an aligned monospace
    block; a wide one a list -- each row's first cell in bold, then one
    "Header: value" line per column. None if `block` is not a table yet
    (mid-stream, before the separator row arrives)."""
    lines = [line.strip() for line in block.strip().splitlines()]
    if len(lines) < 3 or not _SEPARATOR.match(lines[1]):
        return None
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in [lines[0], *lines[2:]]]
    header, body = rows[0], rows[1:]
    plain = [[re.sub(r"[*_`]", "", cell) for cell in row] for row in rows]
    widths = [max(len(row[i]) if i < len(row) else 0 for row in plain) for i in range(len(header))]
    if sum(widths) + 2 * (len(widths) - 1) <= PRE_MAX_WIDTH:
        text = "\n".join("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in plain)
        return f"<pre>{html.escape(text, quote=False)}</pre>"
    cards = []
    for row in body:
        first = re.sub(r"\*\*(.+?)\*\*", r"\1", row[0]) if row else ""
        lines_out = [f"<b>{_inline(html.escape(first, quote=False))}</b>"]
        lines_out += [f"{html.escape(h, quote=False)}: {_inline(html.escape(v, quote=False))}"
                      for h, v in zip(header[1:], row[1:]) if v]
        cards.append("\n".join(lines_out))
    return "\n\n".join(cards) + "\n"


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
        tables: list[str] = []

        def stash(match):
            rendered = _table(match.group(0))
            if rendered is None:
                return match.group(0)
            tables.append(rendered)
            return f"\x00{len(tables) - 1}\x00"

        text = html.escape(_TABLE.sub(stash, part), quote=False)
        text = re.sub(r"^#{1,6}\s+(.+)$", lambda m: f"<b>{m[1].replace('**', '')}</b>", text, flags=re.M)
        text = re.sub(r"^\s*([-*_])(\s*\1){2,}\s*$", "──────────", text, flags=re.M)  # horizontal rule
        text = re.sub(r"^(\s*)[-*]\s+", r"\1• ", text, flags=re.M)
        text = _inline(text)
        out.append(re.sub(r"\x00(\d+)\x00", lambda m: tables[int(m[1])], text))
    return "".join(out)


async def _call(method: str, body: dict, token: Optional[str]) -> Optional[dict]:
    """POST a Bot API method; the response, or None on any failure (logged)."""
    try:
        async with _http(timeout=10.0) as client:
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


async def set_commands(commands: list[dict], token: Optional[str] = None) -> bool:
    """Set the bot's "/" menu. Narrower scopes win in Telegram clients, so
    clear the private/group menus another app may have left behind."""
    for scope in ("all_private_chats", "all_group_chats"):
        await _call("deleteMyCommands", {"scope": {"type": scope}}, token)
    return await _call("setMyCommands", {"commands": commands}, token) is not None


async def set_buttons(chat_id: int, message_id: int, buttons: list[list[dict]], token: Optional[str] = None) -> None:
    """Replace a message's inline buttons (an empty list removes them), leaving its text."""
    await _call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id,
                                           "reply_markup": {"inline_keyboard": buttons}}, token)


async def clear_buttons(chat_id: int, message_id: int, token: Optional[str] = None) -> None:
    await set_buttons(chat_id, message_id, [], token)


async def chat_action(chat_id: int, token: Optional[str] = None) -> None:
    """Shows "typing…" in the chat for ~5 seconds."""
    await _call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, token)


def _plain(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


async def _html_or_plain(method: str, body: dict, text: str, token: Optional[str]) -> Optional[dict]:
    """Send as HTML; if Telegram rejects the markup, the same text without tags."""
    data = await _call(method, {**body, "text": text, "parse_mode": "HTML"}, token)
    return data or await _call(method, {**body, "text": _plain(text)}, token)


async def send_html(chat_id: int, text: str, token: Optional[str] = None,
                    reply_markup: Optional[dict] = None) -> Optional[int]:
    """Send Telegram HTML; the new message's id, or None."""
    body = {"chat_id": chat_id, **({"reply_markup": reply_markup} if reply_markup else {})}
    data = await _html_or_plain("sendMessage", body, text, token)
    return data["result"]["message_id"] if data else None


async def edit_html(chat_id: int, message_id: int, text: str, token: Optional[str] = None) -> None:
    """Replace a message's text; with no reply_markup its buttons go too."""
    await _html_or_plain("editMessageText", {"chat_id": chat_id, "message_id": message_id}, text, token)


async def send_rich(chat_id: int, md: str, token: Optional[str] = None,
                    reply_markup: Optional[dict] = None) -> Optional[int]:
    return await send_html(chat_id, to_html(md), token, reply_markup)


async def draft(chat_id: int, draft_id: int, text: str, token: Optional[str] = None) -> bool:
    """Stream a live, animated preview (Bot API sendMessageDraft, private chats
    only). It is ephemeral: it lasts ~30s and the next sendMessage replaces it.
    Empty text shows Telegram's own "Thinking…" placeholder."""
    body = {"chat_id": chat_id, "draft_id": draft_id}
    return await _html_or_plain("sendMessageDraft", body, text, token) is not None


async def alert(db, user_id: str, text: str) -> bool:
    """The one way to message a user: their own bot if they added one, else
    the server's, to the chat they linked. A no-op for an unlinked user."""
    from backend.guardrails.store import GuardrailStore

    channel = await GuardrailStore(db).telegram_channel(user_id)
    if channel is None:
        return False
    token, chat_id = channel
    return await send(chat_id, text, token)
