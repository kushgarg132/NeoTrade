"""guardrails/telegram.py at the wire: which Bot API method each helper calls,
with which fields, and how answers and failures come back. Written before the
move to aiogram and kept unchanged across it (backend/tests/telegram_wire.py
fakes both transports)."""

import io
import logging

import pytest
from fastapi import HTTPException

from backend.guardrails import telegram
from backend.log_redaction import RedactTokens
from backend.tests.telegram_wire import Refused, TelegramWire, _message

TOKEN = "123456:AAH-own_bot_token"


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setattr(telegram.settings, "TELEGRAM_BOT_TOKEN", "999:server-bot")
    return TelegramWire(monkeypatch)


# -- Linking ---------------------------------------------------------------------

async def test_bot_username_asks_get_me_with_that_bots_token(wire):
    wire.on("getMe", {"id": 1, "is_bot": True, "first_name": "Alerts", "username": "alice_alerts_bot"})
    assert await telegram.bot_username(TOKEN) == "alice_alerts_bot"
    assert (wire.calls[0].token, wire.calls[0].method) == (TOKEN, "getMe")
    await telegram.bot_username()
    assert wire.calls[1].token == "999:server-bot"


async def test_a_token_telegram_rejects_is_a_400_and_is_not_stored(wire):
    from backend.routers import guardrails as router

    wire.on("getMe", status=401, description="Unauthorized")

    class _Store:
        saved = False

        async def set_telegram_bot(self, *args):
            self.saved = True

    store = _Store()
    with pytest.raises(HTTPException) as err:
        await router.telegram_set_bot(router.BotRequest(token=TOKEN), user=type("U", (), {"id": "alice"})(), store=store)
    assert err.value.status_code == 400 and not store.saved


async def test_find_chat_reads_message_updates_for_the_start_code(wire):
    wire.on("getUpdates", [
        {"update_id": 1, "message": _message(1, chat_id=55, text="/start other")},
        {"update_id": 2, "message": _message(2, chat_id=77, text="/start abc123 ")},
        {"update_id": 3, "message": _message(3, chat_id=88, text="hello")},
    ])
    assert await telegram.find_chat("abc123", TOKEN) == 77
    assert await telegram.find_chat("nope", TOKEN) is None
    call = wire.calls[0]
    assert (call.token, call.method, call.params.get("allowed_updates")) == (TOKEN, "getUpdates", ["message"])
    assert "offset" not in call.params


async def test_find_chat_while_the_ai_poller_holds_the_bot_is_none(wire):
    wire.on("getUpdates", status=409, description="Conflict: terminated by other getUpdates request")
    assert await telegram.find_chat("abc123", TOKEN) is None


# -- Long poll ---------------------------------------------------------------------

async def test_updates_long_polls_from_the_offset_and_returns_bot_api_dicts(wire):
    callback = {"id": "cb1", "from": {"id": 42, "is_bot": False, "first_name": "A"}, "chat_instance": "c",
                "data": "nt:confirm:a1", "message": _message(7, text="Buy 10 INFY")}
    wire.on("getUpdates", [{"update_id": 5, "message": _message(3, text="How am I doing?")},
                           {"update_id": 6, "callback_query": callback}])

    batch = await telegram.updates(41, TOKEN, wait=25)

    call = wire.calls[0]
    assert (call.params["offset"], call.params["timeout"]) == ("41", "25")
    assert call.params["allowed_updates"] == ["message", "callback_query"]
    assert batch[0]["update_id"] == 5
    assert (batch[0]["message"]["chat"]["id"], batch[0]["message"]["text"], batch[0]["message"]["date"]) == (
        42, "How am I doing?", 1_790_000_000)
    cb = batch[1]["callback_query"]
    assert (cb["id"], cb["data"], cb["message"]["message_id"], cb["message"]["text"], cb["message"]["chat"]["id"]) == (
        "cb1", "nt:confirm:a1", 7, "Buy 10 INFY", 42)


async def test_updates_without_an_offset_sends_none(wire):
    wire.on("getUpdates", [])
    assert await telegram.updates(None, TOKEN) == []
    assert "offset" not in wire.calls[0].params


async def test_a_failed_poll_raises_and_its_log_line_carries_no_token(wire):
    """The poller logs the failure and backs off (telegram_bot._poll_bot);
    through the production filter neither the line nor its traceback may
    show the bot token."""
    wire.on("getUpdates", status=502, description="Bad Gateway")
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.addFilter(RedactTokens())
    log = logging.getLogger("test.telegram.redaction")
    log.addHandler(handler)
    with pytest.raises(Exception) as err:
        await telegram.updates(None, TOKEN)
    log.warning("telegram polling failed: %s: %s", type(err.value).__name__, err.value, exc_info=err.value)
    log.removeHandler(handler)
    assert "polling failed" in out.getvalue() and "AAH-own_bot_token" not in out.getvalue()


# -- Sending -------------------------------------------------------------------------

async def test_send_is_plain_text_and_true(wire):
    assert await telegram.send(42, "Daily loss limit hit", TOKEN) is True
    assert wire.sent("sendMessage") == [{"chat_id": "42", "text": "Daily loss limit hit"}]


async def test_send_with_the_server_bot_and_with_none_configured(wire, monkeypatch):
    assert await telegram.send(42, "hi") is True
    assert wire.calls[-1].token == "999:server-bot"
    monkeypatch.setattr(telegram.settings, "TELEGRAM_BOT_TOKEN", "")
    assert await telegram.send(42, "hi") is False
    assert len(wire.calls) == 1


async def test_a_failed_send_is_false_not_raised(wire):
    wire.on("sendMessage", status=403, description="Forbidden: bot was blocked by the user")
    assert await telegram.send(42, "hi", TOKEN) is False


async def test_send_buttons_carries_the_inline_keyboard(wire):
    buttons = [[{"text": "Confirm", "callback_data": "nt:confirm:a1"}, {"text": "Cancel", "callback_data": "nt:cancel:a1"}]]
    assert await telegram.send_buttons(42, "Buy 10 INFY", buttons, TOKEN) is True
    (params,) = wire.sent("sendMessage")
    assert params["reply_markup"] == {"inline_keyboard": buttons} and params["text"] == "Buy 10 INFY"


async def test_send_html_returns_the_message_id_and_falls_back_to_plain_text(wire):
    assert await telegram.send_html(42, "<b>Today</b> &amp; more", TOKEN) == 100
    assert wire.sent("sendMessage")[-1] == {"chat_id": "42", "text": "<b>Today</b> &amp; more", "parse_mode": "HTML"}

    wire.on("sendMessage", lambda call: Refused(400, "Bad Request: can't parse entities")
            if call.params.get("parse_mode") else _message(9))
    assert await telegram.send_html(42, "<b>a</b> &lt;b&gt;", TOKEN) == 9
    html_try, plain = wire.sent("sendMessage")[-2:]
    assert html_try["parse_mode"] == "HTML" and "parse_mode" not in plain and plain["text"] == "a <b>"


async def test_edit_html_rearms_or_drops_the_buttons(wire):
    wire.on("editMessageText", _message(7))
    rearm = {"inline_keyboard": [[{"text": "Send real order", "callback_data": "nt:confirm2:a1"}]]}
    await telegram.edit_html(42, 7, "Real money", TOKEN, reply_markup=rearm)
    await telegram.edit_html(42, 7, "✅ Done", TOKEN)
    first, second = wire.sent("editMessageText")
    assert (first["chat_id"], first["message_id"], first["parse_mode"], first["reply_markup"]) == ("42", "7", "HTML", rearm)
    assert "reply_markup" not in second and second["text"] == "✅ Done"


async def test_an_unchanged_edit_is_not_logged(wire, caplog):
    wire.on("editMessageText", status=400, description="Bad Request: message is not modified")
    with caplog.at_level(logging.WARNING):
        await telegram.edit_html(42, 7, "same", TOKEN)
    assert "not modified" not in caplog.text


async def test_buttons_answer_action_draft_and_menu(wire):
    await telegram.set_buttons(42, 7, [[{"text": "Next?", "callback_data": "nt:ask:0"}]], TOKEN)
    await telegram.clear_buttons(42, 7, TOKEN)
    await telegram.answer_callback("cb1", "Paper BUY INFY filled.", TOKEN)
    await telegram.chat_action(42, TOKEN)
    assert await telegram.draft(42, 5, "<i>Thinking…</i>", TOKEN) is True
    assert await telegram.set_commands([{"command": "help", "description": "What I can do"}], TOKEN) is True

    assert [c.method for c in wire.calls] == ["editMessageReplyMarkup", "editMessageReplyMarkup", "answerCallbackQuery",
                                              "sendChatAction", "sendMessageDraft", "deleteMyCommands",
                                              "deleteMyCommands", "setMyCommands"]
    p = [c.params for c in wire.calls]
    assert p[0]["reply_markup"] == {"inline_keyboard": [[{"text": "Next?", "callback_data": "nt:ask:0"}]]}
    assert p[1]["reply_markup"] == {"inline_keyboard": []}
    assert p[2] == {"callback_query_id": "cb1", "text": "Paper BUY INFY filled."}
    assert p[3] == {"chat_id": "42", "action": "typing"}
    assert (p[4]["draft_id"], p[4]["parse_mode"], p[4]["text"]) == ("5", "HTML", "<i>Thinking…</i>")
    assert [x["scope"] for x in p[5:7]] == [{"type": "all_private_chats"}, {"type": "all_group_chats"}]
    assert p[7]["commands"] == [{"command": "help", "description": "What I can do"}]
