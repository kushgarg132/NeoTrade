"""The tool loop every tool-using AI feature shares: the model asks for
facts (backend/ai/facts) as tools, gets them, and answers -- within
`max_rounds`, inside a daily budget, with schema repair and a single-call
fallback so a gateway that rejects tools never leaves a feature empty.
`AI_TOOLS_ENABLED` off sends every caller down its fallback."""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ValidationError

from backend.configs.settings import settings
from backend.engine.session import IST

logger = logging.getLogger(__name__)
CALLS_KEY = "ai:calls:{}"
FINAL_TURN = "Answer now from what you have; no more tools."


async def reserve_ai_call(redis, now: Optional[datetime] = None) -> bool:
    """One model round from today's tool-call allowance (AI_TOOL_CALLS_PER_DAY)."""
    if redis is None:
        return True
    day = (now or datetime.now(timezone.utc)).astimezone(IST).date().isoformat()
    key = CALLS_KEY.format(day)
    used = int(await redis.incrby(key, 1))
    await redis.expire(key, 2 * 86400)
    if used > settings.AI_TOOL_CALLS_PER_DAY:
        await redis.incrby(key, -1)
        return False
    return True


def _text(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):  # some providers return content parts
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return content or ""


def _parse(schema: type[BaseModel], text: str) -> Optional[BaseModel]:
    from backend.components.analyst.agent import _extract_json

    try:
        return schema.model_validate(json.loads(_extract_json(text)))
    except (ValueError, ValidationError):
        return None


async def run_with_tools(task: str, *, system: str, prompt: str, tools: list, tier: str,
                         schema: Optional[type[BaseModel]] = None, max_rounds: int = 4,
                         reserve: Optional[Callable[[], Awaitable[bool]]] = None,
                         fallback: Optional[Callable[[], Awaitable[str]]] = None, llm=None) -> dict:
    result = {"output": None, "tool_trace": [], "rounds": 0, "facts": [], "used_fallback": False}

    async def use_fallback(reason: str) -> dict:
        logger.info("ai %s: single-call fallback (%s)", task, reason)
        if fallback is not None:
            result["output"], result["used_fallback"] = await fallback(), True
        return result

    if not settings.AI_TOOLS_ENABLED:
        return await use_fallback("AI_TOOLS_ENABLED off")
    if llm is None:
        from backend.llm import llm_service

        llm = await llm_service.get_llm(tier=tier)
    if llm is None:
        return await use_fallback("no model configured")

    by_name = {t.name: t for t in tools}
    bound = llm.bind_tools(tools) if tools else llm
    messages = [SystemMessage(content=system), HumanMessage(content=prompt)]

    async def run_call(call: dict) -> ToolMessage:
        began, error = time.monotonic(), None
        tool = by_name.get(call["name"])
        try:
            if tool is None:
                raise KeyError(f"no tool named {call['name']}")
            content = await tool.ainvoke(call.get("args") or {})
            try:
                result["facts"].append(json.loads(content))
            except (TypeError, ValueError):
                pass
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
            content = json.dumps({"error": error})
        result["tool_trace"].append({"tool": call["name"], "args": call.get("args"),
                                     "ms": int((time.monotonic() - began) * 1000), "error": error})
        return ToolMessage(content=content, tool_call_id=call["id"])

    try:
        final = None
        while result["rounds"] < max_rounds:
            if reserve is not None and not await reserve():
                break
            reply = await bound.ainvoke(messages)
            result["rounds"] += 1
            messages.append(reply)
            calls = getattr(reply, "tool_calls", None) or []
            if not calls:
                final = reply
                break
            messages.extend(await asyncio.gather(*(run_call(c) for c in calls)))
        if final is None:
            # Still the tool-bound model: some providers reject tool history
            # with no tools defined. Any further tool calls are ignored.
            final = await bound.ainvoke(messages + [HumanMessage(content=FINAL_TURN)])
            result["rounds"] += 1
            messages.append(final)
        text = _text(final)
        if schema is None:
            result["output"] = text
        else:
            parsed = _parse(schema, text)
            if parsed is None:
                # `messages` already ends with the reply being repaired.
                repair = await bound.ainvoke(messages + [HumanMessage(
                    content=f"Return only valid JSON for this schema: {json.dumps(schema.model_json_schema())}")])
                result["rounds"] += 1
                parsed = _parse(schema, _text(repair))
            result["output"] = parsed
    except Exception as exc:
        logger.warning("ai %s: tool run failed: %s", task, exc)
        return await use_fallback(f"{type(exc).__name__}")
    logger.info("ai %s: %d round(s), tools %s", task, result["rounds"],
                [t["tool"] + ("!" if t["error"] else "") for t in result["tool_trace"]])
    return result
