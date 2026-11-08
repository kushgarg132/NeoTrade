"""ChatOpenAI for Google's OpenAI-compatible endpoint.

Gemini 3 answers each tool call with a thought signature and rejects the next
request (400) unless the signature comes back on that call. langchain-openai
drops the field in both directions, so this class keeps it.

Also records what each call cost: Google has no API for the prepaid balance,
so spend is estimated from tokens and running out shows up only as an error."""

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_openai import ChatOpenAI
from pydantic import PrivateAttr

from backend.database import db as database
from backend.llm import GEMINI_CREDITS_KEY, USER_FEATURES, billed_user, tokens_key

logger = logging.getLogger(__name__)

USAGE_COLLECTION = "gemini_usage"
# USD per 1M tokens as (first day, input, output), oldest first. Thinking bills as output.
# From aistudio.google.com/docs/pricing, read 2026-11-08. A model missing here counts
# tokens but no cost. ponytail: ignores cached-input discounts and 3.1 Pro's dearer
# prompts over 200k tokens, so the estimate can be off; read the bill for exact spend.
PRICES = {
    "gemini-4-argon": [(date.min, 2.00, 10.00), (date(2026, 12, 1), 4.00, 20.00)],
    "gemini-3.8-flash": [(date.min, 0.75, 3.75), (date(2027, 1, 1), 1.50, 7.50)],
    "gemini-3.6-flash": [(date.min, 0.75, 3.75), (date(2027, 1, 1), 1.50, 7.50)],
    "gemini-3.5-flash-lite": [(date.min, 0.30, 2.50)],
    "gemini-3.1-flash-lite": [(date.min, 0.25, 1.50)],
    "gemini-3.1-pro-preview": [(date.min, 2.00, 12.00)],
    "gemini-3-flash-preview": [(date.min, 0.50, 3.00)],
    "gemini-2.5-flash": [(date.min, 0.30, 2.50)],
}


def _today() -> date:
    from backend.engine.session import IST

    return datetime.now(timezone.utc).astimezone(IST).date()


def price(model: str, day: date) -> Optional[tuple[float, float]]:
    """(input, output) USD per 1M tokens on that day, None for a model with no listed price."""
    steps = [(i, o) for first, i, o in PRICES.get(model, []) if first <= day]
    return steps[-1] if steps else None


def _credits_ran_out(error: BaseException) -> bool:
    return getattr(error, "status_code", None) == 402 or "prepayment credits" in f"{error} {getattr(error, 'body', '')}".lower()


class UsageRecorder(AsyncCallbackHandler):
    """Fails open: a store problem must never fail the model call it measures."""

    def __init__(self, model: str, task: Optional[str] = None, feature: Optional[str] = None, gateway: bool = False):
        self.model, self.task, self.feature, self.gateway = model, task, feature, gateway

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        try:
            usage = getattr(response.generations[0][0].message, "usage_metadata", None)
            if usage:
                await self._record(usage)
            if not self.gateway:
                await database.redis.delete(GEMINI_CREDITS_KEY)
        except Exception as exc:
            logger.warning("gemini usage not recorded: %s", exc)

    async def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        if self.gateway or not _credits_ran_out(error):
            return
        try:
            await database.redis.set(GEMINI_CREDITS_KEY, str(int(time.time())), ex=86400)
        except Exception as exc:
            logger.warning("gemini credits flag not set: %s", exc)

    async def _record(self, usage: dict) -> None:
        day = _today()
        input_tokens = usage["input_tokens"]
        output_tokens = usage["total_tokens"] - input_tokens  # output_tokens leaves out thinking
        rate = price(self.model, day)
        cost = (input_tokens * rate[0] + output_tokens * rate[1]) / 1e6 if rate else 0.0
        cached = (usage.get("input_token_details") or {}).get("cache_read") or 0
        thinking = (usage.get("output_token_details") or {}).get("reasoning") or 0
        await database.db[USAGE_COLLECTION].update_one(
            {"_id": f"{day.isoformat()}:{self.model}:{self.task or 'untasked'}"},
            {"$setOnInsert": {"day": day.isoformat(), "model": self.model, "task": self.task, "feature": self.feature,
                              "gateway": self.gateway},
             "$inc": {"calls": 1, "input": input_tokens, "output": output_tokens, "cached": cached, "thinking": thinking,
                      "cost_usd": cost, "unpriced_calls": 0 if rate else 1}},
            upsert=True,
        )
        user_id = billed_user()
        if user_id and self.feature in USER_FEATURES:
            key = tokens_key(user_id, day.isoformat())
            await database.redis.incrby(key, usage["total_tokens"])
            await database.redis.expire(key, 2 * 86400)


# (monotonic time, feature) -> dollars; the ledger is read at most once a minute per process.
_spend: dict[str, tuple[float, float]] = {}
SPEND_CACHE_SECONDS = 60


async def spent_today(feature: str) -> float:
    """Estimated spend today (IST) on one feature, from the ledger. Fails open at 0."""
    at, value = _spend.get(feature, (float("-inf"), 0.0))
    if time.monotonic() - at < SPEND_CACHE_SECONDS or database.db is None:
        return value
    try:
        rows = await database.db[USAGE_COLLECTION].find({"day": _today().isoformat(), "feature": feature}).to_list(None)
        value = sum(r.get("cost_usd", 0.0) for r in rows)
    except Exception as exc:
        logger.warning("spend unreadable for %s: %s", feature, exc)
    _spend[feature] = (time.monotonic(), value)
    return value


def _total(rows: list[dict]) -> dict:
    return {field: sum(r[field] for r in rows) for field in ("calls", "input", "output", "cost_usd")}


async def read_usage(db: Any, redis: Any) -> dict:
    """Estimated spend today and over the last 30 days (IST), per model, and when credits ran out."""
    today = _today()
    rows = await db[USAGE_COLLECTION].find({"day": {"$gte": (today - timedelta(days=29)).isoformat()},
                                            "gateway": {"$ne": True}}).to_list(None)
    models = [{"model": name, **_total([r for r in rows if r["model"] == name])} for name in {r["model"] for r in rows}]
    flagged = await redis.get(GEMINI_CREDITS_KEY) if redis is not None else None
    return {
        "today": _total([r for r in rows if r["day"] == today.isoformat()]),
        "last_30_days": _total(rows),
        "models": sorted(models, key=lambda m: (-m["cost_usd"], -m["calls"])),
        "unpriced_calls": sum(r["unpriced_calls"] for r in rows),
        "depleted_at": datetime.fromtimestamp(int(flagged), timezone.utc).isoformat() if flagged else None,
    }


class GeminiChat(ChatOpenAI):
    # ponytail: held per client, enough because get_llm makes one per agent run and
    # chat history is plain text. Persisted tool turns would need them stored with the messages.
    _signatures: dict = PrivateAttr(default_factory=dict)
    stream_usage: bool = True  # else a streamed reply reports no tokens

    def _remember(self, raw: dict) -> None:
        for choice in raw.get("choices") or []:
            message = choice.get("message") or choice.get("delta") or {}
            for call in message.get("tool_calls") or []:
                signature = ((call.get("extra_content") or {}).get("google") or {}).get("thought_signature")
                if signature and call.get("id"):
                    self._signatures[call["id"]] = signature

    def _create_chat_result(self, response: Any, generation_info: Any = None):
        self._remember(response if isinstance(response, dict) else response.model_dump())
        return super()._create_chat_result(response, generation_info)

    def _convert_chunk_to_generation_chunk(self, chunk: dict, *args: Any, **kwargs: Any):
        self._remember(chunk)
        return super()._convert_chunk_to_generation_chunk(chunk, *args, **kwargs)

    def _get_request_payload(self, input_: Any, *, stop: Any = None, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for message in payload["messages"]:
            for call in message.get("tool_calls") or []:
                if signature := self._signatures.get(call["id"]):
                    call["extra_content"] = {"google": {"thought_signature": signature}}
        return payload
