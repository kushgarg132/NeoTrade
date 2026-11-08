"""Gemini spend is estimated from each response's tokens, and running out of
prepaid credits raises an admin alert (Google has no balance API)."""

from datetime import date

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from mongomock_motor import AsyncMongoMockClient

from backend import gemini_chat
from backend.database import db as database
from backend.llm import GEMINI_CREDITS_KEY


class _Redis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)


class _Depleted(Exception):
    status_code = 402
    body = [{"error": {"message": "Your prepayment credits are depleted."}}]


@pytest.fixture
def stores(monkeypatch):
    monkeypatch.setattr(database, "db", AsyncMongoMockClient()["t"])
    monkeypatch.setattr(database, "redis", _Redis())
    monkeypatch.setattr(gemini_chat, "_today", lambda: date(2026, 11, 8))
    return database


def _result(input_tokens, output_tokens, total_tokens):
    message = AIMessage("x", usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens,
                                             "total_tokens": total_tokens})
    return LLMResult(generations=[[ChatGeneration(message=message)]])


async def _usage(stores):
    return await gemini_chat.read_usage(stores.db, stores.redis)


async def test_thinking_tokens_are_billed_as_output(stores):
    await gemini_chat.UsageRecorder("gemini-3.5-flash-lite").on_llm_end(_result(1000, 100, 1300))
    usage = await _usage(stores)
    assert usage["today"]["output"] == 300
    assert usage["today"]["cost_usd"] == pytest.approx(1000 * 0.30 / 1e6 + 300 * 2.50 / 1e6)


async def test_a_model_with_no_listed_price_counts_tokens_but_no_cost(stores):
    await gemini_chat.UsageRecorder("gemini-flash-latest").on_llm_end(_result(1000, 100, 1100))
    usage = await _usage(stores)
    assert usage["today"]["cost_usd"] == 0
    assert usage["today"]["input"] == 1000
    assert usage["unpriced_calls"] == 1


async def test_prices_step_up_on_the_day_google_published(stores):
    assert gemini_chat.price("gemini-4-argon", date(2026, 11, 30)) == (2.00, 10.00)
    assert gemini_chat.price("gemini-4-argon", date(2026, 12, 1)) == (4.00, 20.00)


async def test_today_is_split_from_the_last_30_days_and_older_days_drop_out(stores, monkeypatch):
    recorder = gemini_chat.UsageRecorder("gemini-3.8-flash")
    for day in (date(2026, 9, 1), date(2026, 11, 1), date(2026, 11, 8)):
        monkeypatch.setattr(gemini_chat, "_today", lambda day=day: day)
        await recorder.on_llm_end(_result(100, 10, 110))
    usage = await _usage(stores)
    assert usage["today"]["calls"] == 1
    assert usage["last_30_days"]["calls"] == 2
    assert usage["models"][0]["model"] == "gemini-3.8-flash"


async def test_depleted_credits_are_flagged_until_a_call_succeeds(stores):
    recorder = gemini_chat.UsageRecorder("gemini-3.8-flash")
    await recorder.on_llm_error(_Depleted("Error code: 402"))
    assert (await _usage(stores))["depleted_at"]
    await recorder.on_llm_end(_result(1, 1, 2))
    assert (await _usage(stores))["depleted_at"] is None


async def test_other_provider_errors_do_not_claim_credits_ran_out(stores):
    await gemini_chat.UsageRecorder("gemini-3.8-flash").on_llm_error(ValueError("Error code: 400"))
    assert GEMINI_CREDITS_KEY not in stores.redis.data


async def test_a_broken_store_never_breaks_the_model_call(stores, monkeypatch):
    monkeypatch.setattr(database, "db", None)
    monkeypatch.setattr(database, "redis", None)
    await gemini_chat.UsageRecorder("gemini-3.8-flash").on_llm_end(_result(1, 1, 2))
    await gemini_chat.UsageRecorder("gemini-3.8-flash").on_llm_error(_Depleted("x"))


class _CountingRedis(_Redis):
    async def incrby(self, key, n):
        self.data[key] = int(self.data.get(key) or 0) + n

    async def expire(self, key, seconds):
        return True


async def test_each_task_has_its_own_ledger_row_with_thinking_and_cached_tokens(stores):
    message = AIMessage("x", usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 150,
                                             "input_token_details": {"cache_read": 40},
                                             "output_token_details": {"reasoning": 40}})
    result = LLMResult(generations=[[ChatGeneration(message=message)]])
    await gemini_chat.UsageRecorder("gemini-3.8-flash", task="news.score", feature="news").on_llm_end(result)
    row = await stores.db[gemini_chat.USAGE_COLLECTION].find_one({"task": "news.score"})
    assert (row["feature"], row["cached"], row["thinking"], row["output"]) == ("news", 40, 40, 50)


async def test_spend_reads_the_ledger_for_that_feature_only(stores):
    gemini_chat._spend.clear()
    await gemini_chat.UsageRecorder("gemini-3.8-flash", task="news.score", feature="news").on_llm_end(_result(1000, 0, 1000))
    await gemini_chat.UsageRecorder("gemini-3.8-flash", task="chat.answer", feature="chat").on_llm_end(_result(9000, 0, 9000))
    assert await gemini_chat.spent_today("news") == pytest.approx(1000 * 0.75 / 1e6)


async def test_a_gateway_call_neither_clears_the_credits_flag_nor_shows_in_the_gemini_sheet(stores):
    stores.redis.data[GEMINI_CREDITS_KEY] = "1"
    await gemini_chat.UsageRecorder("kiro/x", task="chat.answer", feature="chat", gateway=True).on_llm_end(_result(10, 1, 11))
    usage = await _usage(stores)
    assert usage["depleted_at"] and usage["last_30_days"]["calls"] == 0


async def test_tokens_in_a_users_request_count_toward_their_allowance(stores, monkeypatch):
    from backend import llm

    stores.redis = _CountingRedis()
    monkeypatch.setattr(database, "redis", stores.redis)
    with llm.use_model(None, user_id="alice"):
        await gemini_chat.UsageRecorder("gemini-3.8-flash", task="chat.answer", feature="chat").on_llm_end(_result(100, 5, 120))
    assert stores.redis.data[llm.tokens_key("alice", "2026-11-08")] == 120


async def test_a_monthly_spending_cap_raises_the_same_alert(stores):
    error = Exception("Your project has exceeded its monthly spending cap.")
    await gemini_chat.UsageRecorder("gemini-3.8-flash").on_llm_error(error)
    assert (await _usage(stores))["depleted_at"]


def test_only_the_last_streamed_chunk_reports_usage():
    from langchain_core.messages import AIMessageChunk

    llm = gemini_chat.GeminiChat(model="m", api_key="k", base_url="http://x")

    def chunk(text, finish, output):
        raw = {"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": finish}],
               "usage": {"prompt_tokens": 7, "completion_tokens": output, "total_tokens": 7 + output}}
        return llm._convert_chunk_to_generation_chunk(raw, AIMessageChunk, None).message

    merged = chunk("a", None, 2) + chunk("b", None, 22) + chunk("c", "stop", 22)
    assert (merged.usage_metadata["input_tokens"], merged.usage_metadata["output_tokens"]) == (7, 22)
