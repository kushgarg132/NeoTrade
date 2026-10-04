"""The chat agent: a ReAct agent over the user's read tools and propose-only
action tools, with the day snapshot and current page in its system prompt.
Streams thinking, content, and -- when an action tool prepared a card --
an action event the widget draws as a Confirm card. `step` events carry each
tool call's input and completion for clients that show the work (Telegram)."""

import json
import logging
from typing import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from backend.chat.actions import CARD_PREFIX, action_tools
from backend.chat.context import build_snapshot, format_snapshot
from backend.chat.tools import read_tools
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)

TOOL_LABELS = {
    "get_portfolio": "Reading your portfolio", "get_journal": "Reading your journal",
    "get_paper": "Checking the paper engine", "get_decisions": "Reading your proposals",
    "get_limits": "Reading your limits", "explain_index": "Explaining the index",
}


def _text(content) -> str:
    if isinstance(content, list):  # some providers stream parts
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content or "")


def _questions(text: str) -> list[str]:
    """Up to three one-line questions from the model's reply, with any list
    numbering or bullets it added anyway stripped off."""
    lines = (line.strip().lstrip("-*•0123456789.) ").strip().strip('"') for line in text.splitlines())
    return [line for line in lines if line.endswith("?") and len(line) <= 90][:3]


async def suggest_followups(question: str, answer: str) -> list[str]:
    """Next questions worth one tap. Best-effort: any failure means no chips,
    never a broken reply."""
    try:
        system, prompt = render("chat_followups", question=question, answer=answer[-2000:])
        return _questions(await llm_service.get_completion(prompt, system_prompt=system, tier="fast"))
    except Exception as exc:
        logger.warning("chat follow-ups failed: %s", exc)
        return []


async def stream_chat(db, redis, user_id: str, message: str, history: list, context: dict) -> AsyncIterator[dict]:
    llm = await llm_service.get_llm(tier="deep")
    if not llm:
        yield {"type": "content", "data": "The AI service is not available right now."}
        return

    snapshot = await build_snapshot(db, redis, user_id)
    system, page_note = render("chat", snapshot=format_snapshot(snapshot), page=(context or {}).get("page") or "unknown")
    if (context or {}).get("symbol"):
        page_note += f" (looking at {context['symbol']})"
    messages = [SystemMessage(content=f"{system}\n\n{page_note}")]
    for turn in history or []:
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=turn.get("content", "")))
        elif turn.get("role") == "assistant":
            messages.append(AIMessage(content=turn.get("content", "")))
    messages.append(HumanMessage(content=message))

    agent = create_react_agent(llm, read_tools(db, redis, user_id) + action_tools(db, redis, user_id, message))
    answer = ""
    try:
        async for event in agent.astream_events({"messages": messages}, version="v1"):
            kind = event["event"]
            name = event.get("name", "")
            label = TOOL_LABELS.get(name, f"Using {name}")
            if kind == "on_tool_start":
                yield {"type": "thinking", "data": label + "…"}
                yield {"type": "step", "data": {"id": event.get("run_id"), "phase": "start", "label": label,
                                                "input": event["data"].get("input")}}
            elif kind == "on_tool_end":
                yield {"type": "step", "data": {"id": event.get("run_id"), "phase": "end", "label": label}}
                output = event["data"].get("output")
                text = getattr(output, "content", output)
                if isinstance(text, str) and text.startswith(CARD_PREFIX):
                    yield {"type": "action", "data": json.loads(text[len(CARD_PREFIX):])}
            elif kind == "on_chat_model_stream":
                text = _text(event["data"]["chunk"].content)
                if text:
                    answer += text
                    yield {"type": "content", "data": text}
    except Exception as exc:
        logger.error("chat agent failed for %s: %s", user_id, exc)
        yield {"type": "content", "data": f"Something went wrong answering that: {exc}"}
        return

    if answer and (questions := await suggest_followups(message, answer)):
        yield {"type": "suggestions", "data": questions}
