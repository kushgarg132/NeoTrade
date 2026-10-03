"""The chat agent: a ReAct agent over the user's read tools and propose-only
action tools, with the day snapshot and current page in its system prompt.
Streams thinking, content, and -- when an action tool prepared a card --
an action event the widget draws as a Confirm card."""

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


async def stream_chat(db, redis, user_id: str, message: str, history: list, context: dict) -> AsyncIterator[dict]:
    llm = await llm_service.get_llm()
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
    try:
        async for event in agent.astream_events({"messages": messages}, version="v1"):
            kind = event["event"]
            if kind == "on_tool_start":
                yield {"type": "thinking", "data": TOOL_LABELS.get(event["name"], f"Using {event['name']}") + "…"}
            elif kind == "on_tool_end":
                output = event["data"].get("output")
                text = getattr(output, "content", output)
                if isinstance(text, str) and text.startswith(CARD_PREFIX):
                    yield {"type": "action", "data": json.loads(text[len(CARD_PREFIX):])}
            elif kind == "on_chat_model_stream":
                text = _text(event["data"]["chunk"].content)
                if text:
                    yield {"type": "content", "data": text}
    except Exception as exc:
        logger.error("chat agent failed for %s: %s", user_id, exc)
        yield {"type": "content", "data": f"Something went wrong answering that: {exc}"}
