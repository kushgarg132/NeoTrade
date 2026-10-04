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

    assert await telegram_bot.poll_once(db, redis) == 1
    reply.assert_awaited_once_with(db, redis, "alice", 42, "secret-token", "How am I doing?")
    assert redis.set.await_count == 2
    assert "secret-token" not in telegram_bot._offset_key("secret-token")


async def test_telegram_reply_sends_ai_text_and_confirmable_cards(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]

    async def stream(*_args):
        yield {"type": "content", "data": "Your paper engine is stopped."}
        yield {"type": "action", "data": {"id": "a1", "summary": "Start an intraday paper run"}}

    monkeypatch.setattr(telegram_bot.agent, "stream_chat", stream)
    send = AsyncMock(return_value=True)
    buttons = AsyncMock(return_value=True)
    monkeypatch.setattr(telegram_bot.telegram, "send", send)
    monkeypatch.setattr(telegram_bot.telegram, "send_buttons", buttons)

    await telegram_bot._reply(db, None, "alice", 42, "token", "Start the paper engine")

    send.assert_awaited_once_with(42, "Your paper engine is stopped.", "token")
    buttons.assert_awaited_once_with(42, "Start an intraday paper run", [
        [{"text": "Confirm", "callback_data": "nt:confirm:a1"},
         {"text": "Cancel", "callback_data": "nt:cancel:a1"}],
    ], "token")


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
