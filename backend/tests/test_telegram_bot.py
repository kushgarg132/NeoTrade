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
    assert sent == [(
        "<blockquote expandable>💭 <i>Let me check the engine.</i>\n"
        "✅ Checking the paper engine <code>mode=intraday</code></blockquote>\n"
        "Your paper engine is <b>stopped</b>.",
        {"inline_keyboard": [[{"text": "How did it do today?", "callback_data": "nt:ask:0"}]]},
    )]
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

    await telegram_bot._callback(db, None, "alice", 42, "token", {"id": "cb1", "data": "nt:confirm:a1"})

    assert confirmed.await_args.args[3:5] == ("alice", "a1")
    acknowledge.assert_awaited_once_with("cb1", "Paper BUY INFY filled.", "token")
    send.assert_awaited_once_with(42, "Paper BUY INFY filled.", "token")


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
        yield {"type": "suggestions", "data": ["And INFY?"]}

    monkeypatch.setattr(telegram_bot.agent, "stream_chat", stream)
    sent, _ = _fake_bot(monkeypatch)
    clear = AsyncMock()
    monkeypatch.setattr(telegram_bot.telegram, "clear_buttons", clear)

    await telegram_bot._reply(db, redis, "alice", 42, "tok", "Something else")

    clear.assert_awaited_once_with(42, 101, "tok")
    # The new reply's buttons become the ones to clear next time.
    redis.set.assert_any_await(telegram_bot.SUGGEST_LAST_PREFIX + "alice", "101", ex=telegram_bot.HISTORY_SECONDS)
