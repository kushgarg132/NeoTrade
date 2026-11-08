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
