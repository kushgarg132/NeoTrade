"""Telegram alerts. Each user may bring their own bot (a token from
@BotFather, stored encrypted by GuardrailStore); otherwise the
deployment-wide bot (TELEGRAM_BOT_TOKEN) is used, if this server has one.
Linking a user needs no webhook: the app hands out a t.me deep link carrying
a one-time code, the user taps Start, and `find_chat` reads that bot's
recent updates for the code. Every function takes the bot `token`; None
means the deployment-wide bot.

The Bot API transport is aiogram (https://docs.aiogram.dev): one `Bot`, and
so one keep-alive aiohttp session, per token per event loop. Updates and
keyboards cross this module as plain Bot API dicts, so callers never see
aiogram types. A failed call raises aiogram's TelegramAPIError (network
errors included), whose messages carry no token.
"""

import asyncio
import html
import logging
import weakref
import re
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramConflictError
from aiogram.methods import (
    AnswerCallbackQuery, DeleteMyCommands, EditMessageReplyMarkup, EditMessageText, SendChatAction, SendMessage,
    SendMessageDraft, SetMyCommands, TelegramMethod,
)

from backend.configs.settings import settings

logger = logging.getLogger(__name__)
TIMEOUT = 10  # seconds per Bot API call; a long poll adds its own wait


def configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


_BOTS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()  # event loop -> {token: Bot}


def _bot(token: Optional[str] = None) -> Bot:
    """This worker's Bot for `token` (None: the deployment's). Its session is
    reused, not reopened per call (a new HTTPS connection cost ~0.5s that
    taps, drafts and edits all felt), and never closed here."""
    bots = _BOTS.setdefault(asyncio.get_running_loop(), {})
    token = token or settings.TELEGRAM_BOT_TOKEN
    if token not in bots:
        bots[token] = Bot(token)
    return bots[token]


async def bot_username(token: Optional[str] = None) -> str:
    """Also how a pasted token is validated: Telegram rejects a bad one."""
    return (await _bot(token).get_me(request_timeout=TIMEOUT)).username


def start_key(code: str) -> str:
    return f"telegram:start:{code}"


async def find_chat(code: str, token: Optional[str] = None) -> Optional[int]:
    # ponytail: scans the last 100 pending updates; a busy bot needs a webhook instead
    try:
        pending = await _bot(token).get_updates(allowed_updates=["message"], request_timeout=TIMEOUT)
    except TelegramConflictError:
        return None  # the AI poller holds this bot; it stashes Start codes instead
    for update in reversed(pending):
        if update.message and (update.message.text or "").strip() == f"/start {code}":
            return update.message.chat.id
    return None


async def updates(offset: Optional[int] = None, token: Optional[str] = None, wait: int = 0) -> list[dict]:
    """Read a bot's pending updates without logging its token.

    Long polling is deliberately used instead of a public webhook: a user can
    bring their own BotFather bot, whose webhook configuration NeoTrade does
    not own.  Callers persist the next offset after handling each batch.
    """
    # `wait` > 0 is a long poll: Telegram answers as soon as an update arrives.
    batch = await _bot(token).get_updates(offset=offset, timeout=wait, allowed_updates=["message", "callback_query"],
                                          request_timeout=wait + TIMEOUT)
    return [update.model_dump(mode="json", by_alias=True, exclude_none=True) for update in batch]


async def send(chat_id: int, text: str, token: Optional[str] = None, reply_markup: Optional[dict] = None) -> bool:
    """Best effort: a failed alert is logged, never raised into the monitor."""
    if not (token or configured()):
        return False
    return await _call(SendMessage(chat_id=chat_id, text=text, reply_markup=reply_markup or None), token) is not None


async def send_buttons(chat_id: int, text: str, buttons: list[list[dict]], token: Optional[str] = None) -> bool:
    """Send a proposal card. Callback data carries only an opaque action id."""
    return await send(chat_id, text, token, {"inline_keyboard": buttons})


async def answer_callback(callback_id: str, text: str, token: Optional[str] = None) -> None:
    """Dismiss Telegram's button spinner; errors are non-fatal."""
    await _call(AnswerCallbackQuery(callback_query_id=callback_id, text=text), token)


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


async def _call(method: TelegramMethod, token: Optional[str]):
    """Run one Bot API method; its result, or None on any failure (logged)."""
    try:
        return await _bot(token)(method, request_timeout=TIMEOUT)
    except TelegramAPIError as exc:
        # An edit with unchanged text is harmless; anything else is worth a line.
        if "not modified" not in exc.message:
            logger.warning("telegram %s failed: %s", method.__api_method__, exc.message)
    except Exception as exc:
        logger.warning("telegram %s failed: %s", method.__api_method__, type(exc).__name__)
    return None


async def set_commands(commands: list[dict], token: Optional[str] = None) -> bool:
    """Set the bot's "/" menu. Narrower scopes win in Telegram clients, so
    clear the private/group menus another app may have left behind."""
    for scope in ("all_private_chats", "all_group_chats"):
        await _call(DeleteMyCommands(scope={"type": scope}), token)
    return await _call(SetMyCommands(commands=commands), token) is not None


async def set_buttons(chat_id: int, message_id: int, buttons: list[list[dict]], token: Optional[str] = None) -> None:
    """Replace a message's inline buttons (an empty list removes them), leaving its text."""
    await _call(EditMessageReplyMarkup(chat_id=chat_id, message_id=message_id,
                                       reply_markup={"inline_keyboard": buttons}), token)


async def clear_buttons(chat_id: int, message_id: int, token: Optional[str] = None) -> None:
    await set_buttons(chat_id, message_id, [], token)


async def chat_action(chat_id: int, token: Optional[str] = None) -> None:
    """Shows "typing…" in the chat for ~5 seconds."""
    await _call(SendChatAction(chat_id=chat_id, action="typing"), token)


def _plain(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


async def _html_or_plain(method: type, body: dict, text: str, token: Optional[str]):
    """Send as HTML; if Telegram rejects the markup, the same text without tags."""
    result = await _call(method(**body, text=text, parse_mode="HTML"), token)
    return result if result is not None else await _call(method(**body, text=_plain(text)), token)


async def send_html(chat_id: int, text: str, token: Optional[str] = None,
                    reply_markup: Optional[dict] = None) -> Optional[int]:
    """Send Telegram HTML; the new message's id, or None."""
    message = await _html_or_plain(SendMessage, {"chat_id": chat_id, "reply_markup": reply_markup or None}, text, token)
    return message.message_id if message else None


async def edit_html(chat_id: int, message_id: int, text: str, token: Optional[str] = None,
                    reply_markup: Optional[dict] = None) -> None:
    """Replace a message's text; with no reply_markup its buttons go too."""
    await _html_or_plain(EditMessageText, {"chat_id": chat_id, "message_id": message_id,
                                           "reply_markup": reply_markup or None}, text, token)


async def send_rich(chat_id: int, md: str, token: Optional[str] = None,
                    reply_markup: Optional[dict] = None) -> Optional[int]:
    return await send_html(chat_id, to_html(md), token, reply_markup)


async def draft(chat_id: int, draft_id: int, text: str, token: Optional[str] = None) -> bool:
    """Stream a live, animated preview (Bot API sendMessageDraft, private chats
    only). It is ephemeral: it lasts ~30s and the next sendMessage replaces it.
    Empty text shows Telegram's own "Thinking…" placeholder."""
    return await _html_or_plain(SendMessageDraft, {"chat_id": chat_id, "draft_id": draft_id}, text, token) is not None


async def alert(db, user_id: str, text: str, html: bool = False) -> bool:
    """The one way to message a user: their own bot if they added one, else
    the server's, to the chat they linked. A no-op for an unlinked user.
    `html`: the text is Telegram HTML (tags, escaped data); plain `send`
    would show the tags and break links on their &amp;."""
    from backend.guardrails.store import GuardrailStore

    channel = await GuardrailStore(db).telegram_channel(user_id)
    if channel is None:
        return False
    token, chat_id = channel
    if html:
        return await send_html(chat_id, text, token) is not None
    return await send(chat_id, text, token)
