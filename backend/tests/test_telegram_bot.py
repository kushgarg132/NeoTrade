from unittest.mock import AsyncMock

from mongomock_motor import AsyncMongoMockClient

from backend.guardrails import telegram_bot


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
    assert redis.set.await_count == 2
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

    async def stream(*_args):
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

    async def stream(*_args):
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


async def test_live_card_asks_for_a_second_tap_then_sends(monkeypatch):
    """Real money takes two taps in Telegram too: the first re-arms the card
    with a Send button, the second confirms with second_tap."""
    db = AsyncMongoMockClient()["test_db"]
    confirmed = AsyncMock(side_effect=[
        {"status": "NEEDS_SECOND_TAP", "result": "Real money. Tap Confirm again to send it."},
        {"status": "CONFIRMED", "result": "Live BUY INFY sent."},
    ])
    monkeypatch.setattr(telegram_bot, "confirm", confirmed)
    monkeypatch.setattr(telegram_bot.telegram, "answer_callback", AsyncMock())
    edit = AsyncMock()
    monkeypatch.setattr(telegram_bot.telegram, "edit_html", edit)
    card = {"message_id": 7, "text": "Buy 10 INFY with real money"}

    await telegram_bot._callback(db, None, "alice", 42, "token", {"id": "cb1", "data": "nt:confirm:a1", "message": card})
    assert confirmed.await_args_list[0].kwargs.get("second_tap", False) is False
    text, markup = edit.await_args.args[2], edit.await_args.kwargs["reply_markup"]
    assert "✅" not in text and "Real money" in text
    assert markup["inline_keyboard"][0][0]["callback_data"] == "nt:confirm2:a1"

    await telegram_bot._callback(db, None, "alice", 42, "token", {"id": "cb2", "data": "nt:confirm2:a1", "message": card})
    assert confirmed.await_args_list[1].kwargs["second_tap"] is True
    assert edit.await_args.args[2].endswith("✅ Live BUY INFY sent.")


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

    async def stream(_db, _redis, _user, _text, history, _context):
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

    async def stream(_db, _redis, _user, text, *_rest):
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

    async def stream(*_args):
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

    async def stream(*_args):
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


async def test_telegram_calls_share_one_keep_alive_client(monkeypatch):
    import httpx

    from backend.guardrails import telegram

    made = []

    def new_client():
        made.append(1)
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})))

    monkeypatch.setattr(telegram, "_new_client", new_client)
    monkeypatch.setattr(telegram, "_CLIENTS", __import__("weakref").WeakKeyDictionary())
    await telegram.answer_callback("c1", "", "tok")
    await telegram.chat_action(42, "tok")
    await telegram.answer_callback("c2", "", "tok")
    assert len(made) == 1  # no new TLS handshake per call
