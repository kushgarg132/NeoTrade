from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.guardrails import telegram_bot
from backend.tests.test_chat_actions import _propose, env  # noqa: F401 (fixture)


async def test_poll_only_answers_a_chat_linked_to_that_bot(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = AsyncMock()
    redis.get.return_value = None
    monkeypatch.setattr(telegram_bot.GuardrailStore, "telegram_routes", AsyncMock(return_value=[("secret-token", {42: "alice"})]))
    monkeypatch.setattr(telegram_bot.telegram, "updates", AsyncMock(return_value=[
        {"update_id": 5, "message": {"chat": {"id": 42}, "text": "How am I doing?"}},
        {"update_id": 6, "message": {"chat": {"id": 99}, "text": "Let me trade"}},
    ]))
    reply = AsyncMock()
    monkeypatch.setattr(telegram_bot, "_reply", reply)
    menu = AsyncMock(return_value=True)
    monkeypatch.setattr(telegram_bot.telegram, "set_commands", menu)

    assert await telegram_bot.poll_once(db, redis) == 1
    menu.assert_awaited_once_with(telegram_bot.COMMANDS, "secret-token")
    reply.assert_awaited_once_with(db, redis, "alice", 42, "secret-token", "How am I doing?")
    # One per-bot worker lock plus one offset for the whole batch, committed
    # before any slow AI reply so another worker cannot re-fetch it.
    assert len([c for c in redis.set.await_args_list if not c.args[0].startswith("rate:")]) == 2  # rate-limit windows also use set
    redis.set.assert_any_await(telegram_bot._offset_key("secret-token"), "7")
    assert "secret-token" not in telegram_bot._offset_key("secret-token")


def _fake_bot(monkeypatch):
    sent, drafts = [], []

    async def send_html(chat_id, text, token=None, markup=None):
        sent.append((text, markup))
        return 100 + len(sent)

    async def draft(chat_id, draft_id, text, token=None):
        drafts.append(text)
        return True

    monkeypatch.setattr(telegram_bot.telegram, "send_html", send_html)
    monkeypatch.setattr(telegram_bot.telegram, "draft", draft)
    monkeypatch.setattr(telegram_bot.telegram, "chat_action", AsyncMock())
    monkeypatch.setattr(telegram_bot.telegram, "set_buttons", AsyncMock())
    monkeypatch.setattr(telegram_bot.PrefsStore, "get", AsyncMock(return_value={}))
    return sent, drafts


async def test_telegram_reply_shows_work_then_answer_cards_and_suggestions(monkeypatch):
    import asyncio

    db = AsyncMongoMockClient()["test_db"]
    redis = AsyncMock()
    redis.get.return_value = None
    monkeypatch.setattr(telegram_bot, "DRAFT_SECONDS", 0.01)

    async def stream(*_args, **_kw):
        yield {"type": "content", "data": "Let me check the engine."}
        yield {"type": "step", "data": {"id": "r1", "phase": "start", "label": "Checking the paper engine",
                                        "input": {"mode": "intraday"}}}
        await asyncio.sleep(0.05)  # let the live draft redraw mid-tool
        yield {"type": "step", "data": {"id": "r1", "phase": "end", "label": "Checking the paper engine"}}
        yield {"type": "content", "data": "Your paper engine is **stopped**."}
        yield {"type": "action", "data": {"id": "a1", "summary": "Start an intraday paper run"}}
        yield {"type": "answer_end", "data": None}
        yield {"type": "suggestions", "data": ["How did it do today?"]}

    monkeypatch.setattr(telegram_bot.agent, "stream_chat", stream)
    sent, drafts = _fake_bot(monkeypatch)
    buttons = AsyncMock(return_value=True)
    monkeypatch.setattr(telegram_bot.telegram, "send_buttons", buttons)

    await telegram_bot._reply(db, redis, "alice", 42, "token", "Start the paper engine")

    # The live draft showed the reasoning and the running tool with its input.
    assert any("💭 <i>Let me check the engine.</i>" in d and "⏳ Checking the paper engine <code>mode=intraday</code>" in d
               for d in drafts)
    # The final message keeps the work, collapsed, above the formatted answer.
    # It goes out at answer_end; the suggestions are attached to it afterwards.
    assert sent == [(
        "<blockquote expandable>💭 <i>Let me check the engine.</i>\n"
        "✅ Checking the paper engine <code>mode=intraday</code></blockquote>\n"
        "Your paper engine is <b>stopped</b>.",
        None,
    )]
    telegram_bot.telegram.set_buttons.assert_awaited_once_with(
        42, 101, [[{"text": "How did it do today?", "callback_data": "nt:ask:0"}]], "token")
    redis.set.assert_any_await(f"{telegram_bot.SUGGEST_PREFIX}alice:101", '["How did it do today?"]',
                               ex=telegram_bot.HISTORY_SECONDS)
    buttons.assert_awaited_once_with(42, "Start an intraday paper run", [
        [{"text": "Confirm", "callback_data": "nt:confirm:a1"},
         {"text": "Cancel", "callback_data": "nt:cancel:a1"}],
    ], "token")


async def test_long_answer_continues_in_a_new_message(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]

    async def stream(*_args, **_kw):
        for _ in range(40):  # 4000 chars, over MESSAGE_LIMIT
            yield {"type": "content", "data": "x" * 99 + "\n"}

    monkeypatch.setattr(telegram_bot.agent, "stream_chat", stream)
    sent, _ = _fake_bot(monkeypatch)

    await telegram_bot._reply(db, None, "alice", 42, "token", "Explain everything")

    assert len(sent) == 2 and all(len(text) <= telegram_bot.MESSAGE_LIMIT for text, _ in sent)


async def test_tapped_suggestion_is_asked(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = AsyncMock()
    redis.get.return_value = '["How did it do today?"]'
    monkeypatch.setattr(telegram_bot.telegram, "answer_callback", AsyncMock())
    monkeypatch.setattr(telegram_bot.telegram, "send_rich", AsyncMock(return_value=7))
    reply = AsyncMock()
    monkeypatch.setattr(telegram_bot, "_reply", reply)

    await telegram_bot._callback(db, redis, "alice", 42, "tok",
                                 {"id": "cb", "data": "nt:ask:0", "message": {"message_id": 101}})

    redis.get.assert_awaited_once_with(f"{telegram_bot.SUGGEST_PREFIX}alice:101")
    reply.assert_awaited_once_with(db, redis, "alice", 42, "tok", "How did it do today?")


def test_markdown_becomes_telegram_html():
    md = "## **Today**\n- **INFY** +₹120\nsee `get_portfolio` & _note_ [app](https://x.io/?a=1&b=2)\nsnake_case *open"
    assert telegram_bot.telegram.to_html(md) == (
        "<b>Today</b>\n• <b>INFY</b> +₹120\nsee <code>get_portfolio</code> &amp; <i>note</i> "
        '<a href="https://x.io/?a=1&amp;b=2">app</a>\nsnake_case *open')


async def test_callback_uses_existing_confirm_path(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    confirmed = AsyncMock(return_value={"status": "CONFIRMED", "result": "Paper BUY INFY filled."})
    monkeypatch.setattr(telegram_bot, "confirm", confirmed)
    acknowledge = AsyncMock()
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(telegram_bot.telegram, "answer_callback", acknowledge)
    monkeypatch.setattr(telegram_bot.telegram, "send", send)

    edit = AsyncMock()
    monkeypatch.setattr(telegram_bot.telegram, "edit_html", edit)

    await telegram_bot._callback(db, None, "alice", 42, "token", {
        "id": "cb1", "data": "nt:confirm:a1", "message": {"message_id": 7, "text": "Buy 10 INFY on paper"}})

    assert confirmed.await_args.args[3:5] == ("alice", "a1")
    acknowledge.assert_awaited_once_with("cb1", "Paper BUY INFY filled.", "token")
    # The card itself shows the outcome and loses its buttons; no extra message.
    edit.assert_awaited_once_with(42, 7, "Buy 10 INFY on paper\n\n✅ Paper BUY INFY filled.", "token")
    send.assert_not_awaited()


async def test_live_card_needs_two_server_checked_taps(env, monkeypatch, caplog):
    """End to end with the real confirm: the first tap places nothing and
    re-arms the card with a Send button carrying a one-time token; a second
    tap without that token, or with a forged one, places nothing; the real
    one places exactly one order and cannot be replayed."""
    db = env["db"]
    card = await _propose(db, "propose_order", {"symbol": "INFY", "side": "BUY", "quantity": 10, "venue": "live"})
    monkeypatch.setattr(telegram_bot, "get_credential_store", lambda: None)
    monkeypatch.setattr(telegram_bot.telegram, "answer_callback", AsyncMock())
    edit = AsyncMock()
    monkeypatch.setattr(telegram_bot.telegram, "edit_html", edit)
    message = {"message_id": 7, "text": "Buy 10 INFY with real money"}

    async def tap(data):
        await telegram_bot._callback(db, None, "alice", 42, "token", {"id": "cb", "data": data, "message": message})
        return edit.await_args

    first = await tap(f"nt:confirm:{card['id']}")
    send = first.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    assert "Real money" in first.args[2] and env["broker"].placed == []
    assert send.startswith(f"nt:confirm2:{card['id']}.") and len(send.encode()) <= 64

    await tap(f"nt:confirm2:{card['id']}")  # no token: just re-armed
    caplog.set_level("INFO")
    forged = await tap(f"nt:confirm2:{card['id']}.forged")
    assert "confirm_expired" in caplog.text  # the refusal code, beside the card text
    assert env["broker"].placed == []
    assert forged.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"nt:confirm:{card['id']}"

    assert (await tap(send)).args[2].endswith("✅ Sent to your broker: filled, 10 of 10 filled.")
    await tap(send)
    assert len(env["broker"].placed) == 1


async def test_start_code_is_stashed_for_settings_link_flow(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = AsyncMock()
    redis.get.return_value = None
    monkeypatch.setattr(telegram_bot.GuardrailStore, "telegram_routes", AsyncMock(return_value=[("tok", {42: "alice"})]))
    monkeypatch.setattr(telegram_bot.telegram, "updates", AsyncMock(return_value=[
        {"update_id": 1, "message": {"chat": {"id": 77}, "text": "/start abc123"}},
    ]))
    monkeypatch.setattr(telegram_bot.telegram, "set_commands", AsyncMock(return_value=True))

    assert await telegram_bot.poll_once(db, redis) == 0
    redis.set.assert_any_await(telegram_bot.telegram.start_key("abc123"), "77", ex=telegram_bot.START_SECONDS)


async def test_reply_passes_and_saves_conversation_history(monkeypatch):
    import json

    db = AsyncMongoMockClient()["test_db"]
    redis = AsyncMock()
    earlier = [{"role": "user", "content": "Any proposals?"}, {"role": "assistant", "content": "One: buy INFY."}]
    redis.get.side_effect = lambda key: json.dumps(earlier) if key.startswith(telegram_bot.HISTORY_PREFIX) else None
    seen = {}

    async def stream(_db, _redis, _user, _text, history, _context, **_kw):
        seen["history"] = history
        yield {"type": "content", "data": "Prepared."}

    monkeypatch.setattr(telegram_bot.agent, "stream_chat", stream)
    _fake_bot(monkeypatch)

    await telegram_bot._reply(db, redis, "alice", 42, "tok", "Yes, approve it")

    assert seen == {"history": earlier}
    saved = json.loads(redis.set.await_args_list[0].args[1])
    assert saved[-2:] == [{"role": "user", "content": "Yes, approve it"}, {"role": "assistant", "content": "Prepared."}]


def test_reasoning_lines_render_markdown():
    html = telegram_bot._steps_html([{"think": "Confirm via the **Confirm button**."}])
    assert html == "💭 <i>Confirm via the <b>Confirm button</b>.</i>"


def test_on_off_setting_accepts_a_coerced_one():
    from backend.chat.actions import _setting

    # The tool schema Union[float, bool, str] turns a JSON 1 into 1.0.
    assert _setting("guardrails_enabled", 1.0) is True
    assert _setting("guardrails_enabled", 0.0) is False


async def test_shortcut_command_asks_the_ai_and_new_clears_memory(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = AsyncMock()
    redis.get.return_value = None
    asked = []

    async def stream(_db, _redis, _user, text, *_rest, **_kw):
        asked.append(text)
        yield {"type": "content", "data": "Up 2%."}

    monkeypatch.setattr(telegram_bot.agent, "stream_chat", stream)
    _fake_bot(monkeypatch)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(telegram_bot.telegram, "send", send)

    await telegram_bot._reply(db, redis, "alice", 42, "tok", "/portfolio@NeoBot INFY")
    assert asked == ["How is my portfolio doing? Focus on: INFY"]

    await telegram_bot._reply(db, redis, "alice", 42, "tok", "/new")
    redis.delete.assert_awaited_once_with(telegram_bot.HISTORY_PREFIX + "alice")

    await telegram_bot._reply(db, redis, "alice", 42, "tok", "/codex")
    assert "/portfolio — Portfolio summary" in send.await_args.args[1]


async def test_new_message_removes_the_previous_suggestions(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = AsyncMock()
    redis.get.side_effect = lambda key: "101" if key == telegram_bot.SUGGEST_LAST_PREFIX + "alice" else None

    async def stream(*_args, **_kw):
        yield {"type": "content", "data": "Sure."}
        yield {"type": "answer_end", "data": None}
        yield {"type": "suggestions", "data": ["And INFY?"]}

    monkeypatch.setattr(telegram_bot.agent, "stream_chat", stream)
    sent, _ = _fake_bot(monkeypatch)
    clear = AsyncMock()
    monkeypatch.setattr(telegram_bot.telegram, "clear_buttons", clear)

    await telegram_bot._reply(db, redis, "alice", 42, "tok", "Something else")

    clear.assert_awaited_once_with(42, 101, "tok")
    # The new reply's buttons become the ones to clear next time.
    redis.set.assert_any_await(telegram_bot.SUGGEST_LAST_PREFIX + "alice", "101", ex=telegram_bot.HISTORY_SECONDS)


USAGE = {
    "key_name": "neotrade",
    "tokens": {"input": 1200000, "output": 34000, "reasoning": 0, "total": 1234000},
    "cost": {"used_usd": 1.5, "limit_usd": None, "reset_at": None},
    "providers": [
        {"provider": "claude", "plan": "Max", "pools": [
            {"label": "Claude & GPT", "remaining_pct": 62, "reset_at": None, "models": ["claude-opus", "gpt-5"]},
            {"label": "Claude & GPT · weekly", "remaining_pct": 12, "reset_at": None, "models": []},
        ]},
        {"provider": "empty", "plan": None, "pools": []},
    ],
}


def test_usage_message_mirrors_the_settings_sheet():
    text = telegram_bot._usage_html(USAGE)
    assert "<b>Usage</b> · Key neotrade" in text
    assert "This month, this app's key" in text and "<b>1,234,000 tokens</b>" in text
    assert "Input 1,200,000 · Output 34,000 · Reasoning 0" in text
    assert "Cost $1.50 · no cost limit" in text
    assert "Providers · quota left" in text and "<b>claude</b> Max" in text
    assert "▓▓▓▓▓▓░░░░ 62% left" in text and "2 models" in text
    assert "🔴" in text  # under 20% left
    assert "<blockquote expandable>claude-opus, gpt-5</blockquote>" in text
    assert "empty" not in text  # providers with no pools are hidden, like the UI


async def test_usage_command_is_admin_only(monkeypatch):
    from datetime import datetime, timezone

    db = AsyncMongoMockClient()["test_db"]
    for uid, role in (("alice", "admin"), ("bob", "user")):
        await db["users"].insert_one({"id": uid, "google_sub": uid, "email": f"{uid}@x.io", "name": uid,
                                      "picture": None, "role": role, "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc)})
    monkeypatch.setattr(telegram_bot, "fetch_usage", AsyncMock(return_value=USAGE))
    sent = AsyncMock(return_value=1)
    monkeypatch.setattr(telegram_bot.telegram, "send_html", sent)
    plain = AsyncMock(return_value=True)
    monkeypatch.setattr(telegram_bot.telegram, "send", plain)

    await telegram_bot._reply(db, None, "alice", 42, "tok", "/usage")
    assert "Key neotrade" in sent.await_args.args[1]
    await telegram_bot._reply(db, None, "bob", 43, "tok", "/usage")
    plain.assert_awaited_once_with(43, "Usage is for administrators.", "tok")
    assert {"command": "usage", "description": "Gateway usage (admins)"} in telegram_bot.COMMANDS


async def test_typing_is_sent_even_when_drafts_are_accepted(monkeypatch):
    # Some Telegram apps accept drafts but never show them; "typing…" must still appear.
    import asyncio

    db = AsyncMongoMockClient()["test_db"]

    async def stream(*_args, **_kw):
        await asyncio.sleep(0.05)
        yield {"type": "content", "data": "Hi."}

    monkeypatch.setattr(telegram_bot.agent, "stream_chat", stream)
    monkeypatch.setattr(telegram_bot, "DRAFT_SECONDS", 0.01)
    _fake_bot(monkeypatch)

    await telegram_bot._reply(db, None, "alice", 42, "tok", "hello")

    telegram_bot.telegram.chat_action.assert_awaited_with(42, "tok")


def test_a_narrow_table_becomes_an_aligned_monospace_block():
    md = "Losers:\n\n| Stock | P&L |\n|---|---|\n| **TCS** | −2% |\n| INFY | +1.5% |\n\nDone."
    out = telegram_bot.telegram.to_html(md)
    assert "<pre>Stock  P&amp;L\nTCS    −2%\nINFY   +1.5%</pre>" in out
    assert "|" not in out and out.startswith("Losers:") and out.endswith("Done.")


def test_a_wide_table_becomes_a_list_of_rows():
    md = ("| Stock | Weight | P&L % | Likely Drag |\n|---|---|---|---|\n"
          "| **MID150BEES** | 25.2% | −1.97% | Largest holding, even a small dip hurts the most |\n"
          "| GOLDBEES | 9.4% | −7.77% | Gold ETF pulled back meaningfully |")
    out = telegram_bot.telegram.to_html(md)
    assert "|" not in out and "<pre>" not in out
    assert "<b>MID150BEES</b>\nWeight: 25.2%\nP&amp;L %: −1.97%\nLikely Drag: Largest holding" in out
    assert "\n\n<b>GOLDBEES</b>\nWeight: 9.4%" in out


def test_an_unfinished_table_mid_stream_is_left_as_text():
    assert telegram_bot.telegram.to_html("| Stock | P&L |") == "| Stock | P&amp;L |"


def test_a_horizontal_rule_becomes_a_divider_not_dashes():
    out = telegram_bot.telegram.to_html("Above\n\n---\n\nBelow\n- item")
    assert "---" not in out and "──────" in out and "• item" in out


def test_short_suggestions_pair_up_two_per_row():
    rows = telegram_bot._suggestion_rows(["📊 vs Nifty?", "🎯 Set risk level", "🔍 Which proposals fit my plan best?"])
    assert [[b["text"] for b in row] for row in rows] == [
        ["📊 vs Nifty?", "🎯 Set risk level"], ["🔍 Which proposals fit my plan best?"]]
    assert [b["callback_data"] for row in rows for b in row] == ["nt:ask:0", "nt:ask:1", "nt:ask:2"]


def test_draft_says_thinking_before_the_first_words():
    assert telegram_bot._draft_html({"steps": [], "text": ""}) == "💭 <i>Thinking…</i>"
    assert "Thinking" not in telegram_bot._draft_html({"steps": [], "text": "Hello"})


async def test_telegram_calls_share_one_bot_per_token():
    from backend.guardrails import telegram

    # One Bot, so one keep-alive session: no new TLS handshake per call.
    assert telegram._bot("1:a") is telegram._bot("1:a")
    assert telegram._bot("1:a") is not telegram._bot("2:b")


async def test_failed_poll_backs_off_instead_of_hammering(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = AsyncMock()
    redis.get.return_value = None
    monkeypatch.setattr(telegram_bot.GuardrailStore, "telegram_routes", AsyncMock(return_value=[("tok", {42: "alice"})]))
    monkeypatch.setattr(telegram_bot.telegram, "updates", AsyncMock(side_effect=RuntimeError("502 Bad Gateway")))
    monkeypatch.setattr(telegram_bot.telegram, "set_commands", AsyncMock(return_value=True))
    sleep = AsyncMock()
    monkeypatch.setattr(telegram_bot.asyncio, "sleep", sleep)

    assert await telegram_bot.poll_once(db, redis) == 0
    sleep.assert_awaited_once_with(telegram_bot.FAIL_BACKOFF_SECONDS)
    assert telegram_bot.FAIL_BACKOFF_SECONDS == 10 < telegram_bot.LOCK_SECONDS


async def test_taps_route_only_from_the_linked_private_chat(monkeypatch):
    """A Confirm tap counts only from the chat linked to that bot's user:
    not from another chat, and never from a group (any member could tap)."""
    db = AsyncMongoMockClient()["test_db"]
    redis = AsyncMock()
    redis.get.return_value = None
    monkeypatch.setattr(telegram_bot.GuardrailStore, "telegram_routes",
                        AsyncMock(return_value=[("tok", {42: "alice", -42: "alice"})]))

    def tap(update_id, chat_id):
        return {"update_id": update_id, "callback_query": {
            "id": f"cb{update_id}", "data": "nt:confirm:a1", "message": {"message_id": 7, "chat": {"id": chat_id}}}}

    monkeypatch.setattr(telegram_bot.telegram, "updates", AsyncMock(return_value=[tap(1, 99), tap(2, -42), tap(3, 42)]))
    monkeypatch.setattr(telegram_bot.telegram, "set_commands", AsyncMock(return_value=True))
    callback = AsyncMock()
    monkeypatch.setattr(telegram_bot, "_callback", callback)

    assert await telegram_bot.poll_once(db, redis) == 1
    (args, _), = callback.await_args_list
    assert args[2:5] == ("alice", 42, "tok") and args[5]["id"] == "cb3"


@pytest.mark.parametrize("data", ["nt:confirm", "nt:", "other:confirm:a1", "", "nt:delete:a1"])
async def test_malformed_or_foreign_callback_data_does_nothing(monkeypatch, data):
    db = AsyncMongoMockClient()["test_db"]
    confirmed = AsyncMock()
    monkeypatch.setattr(telegram_bot, "confirm", confirmed)
    for name in ("answer_callback", "edit_html", "send"):
        monkeypatch.setattr(telegram_bot.telegram, name, AsyncMock())
    await telegram_bot._callback(db, None, "alice", 42, "tok", {"id": "cb", "data": data, "message": {"message_id": 7}})
    confirmed.assert_not_awaited()
    telegram_bot.telegram.edit_html.assert_not_awaited()


async def test_charts_and_images_go_out_as_photos_before_the_answer(monkeypatch):
    import base64

    db = AsyncMongoMockClient()["test_db"]
    asked = {}

    async def stream(*_args, **kwargs):
        asked.update(kwargs)
        yield {"type": "chart", "data": {"title": "P&L", "kind": "bar", "unit": "₹", "labels": ["a", "b"],
                                         "series": [{"name": "x", "values": [1, 2]}]}}
        yield {"type": "image", "data": {"url": "data:image/png;base64," + base64.b64encode(b"img").decode(), "alt": "a bull"}}
        yield {"type": "image", "data": {"url": "https://x.test/i.png", "alt": "a bear"}}
        yield {"type": "content", "data": "Here you go."}
        yield {"type": "answer_end", "data": None}

    order, photos = [], []

    async def send_photo(chat_id, photo, caption="", token=None):
        photos.append((photo, caption))
        order.append("photo")
        return True

    monkeypatch.setattr(telegram_bot.agent, "stream_chat", stream)
    monkeypatch.setattr(telegram_bot, "render_png", lambda spec: b"png:" + spec["title"].encode())
    sent, _ = _fake_bot(monkeypatch)
    monkeypatch.setattr(telegram_bot.telegram, "send_photo", send_photo)

    await telegram_bot._reply(db, None, "alice", 42, "token", "Chart my P&L and draw a bull")

    assert asked.get("media") is True
    assert photos == [(b"png:P&L", "P&L"), (b"img", "a bull"), ("https://x.test/i.png", "a bear")]
    assert len(sent) == 1 and sent[0][0].endswith("Here you go.")


async def test_a_failed_chart_says_so_and_the_answer_still_arrives(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]

    async def stream(*_args, **_kw):
        yield {"type": "chart", "data": {"title": "P&L", "kind": "bar", "unit": "", "labels": ["a"],
                                         "series": [{"name": "x", "values": [1]}]}}
        yield {"type": "content", "data": "Done."}
        yield {"type": "answer_end", "data": None}

    def boom(spec):
        raise RuntimeError("no fonts")

    monkeypatch.setattr(telegram_bot.agent, "stream_chat", stream)
    monkeypatch.setattr(telegram_bot, "render_png", boom)
    sent, _ = _fake_bot(monkeypatch)
    monkeypatch.setattr(telegram_bot.telegram, "send_photo", AsyncMock(return_value=True))

    await telegram_bot._reply(db, None, "alice", 42, "token", "Chart it")

    telegram_bot.telegram.send_photo.assert_not_awaited()
    assert sent[0][0] == "Could not draw the chart “P&amp;L”."
    assert sent[-1][0].endswith("Done.")
