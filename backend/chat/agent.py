"""The chat agent: a ReAct agent over the user's read tools and propose-only
action tools, with the day snapshot and current page in its system prompt.
Streams thinking, content, and -- when an action tool prepared a card --
an action event the widget draws as a Confirm card. `step` events carry each
tool call's input and completion for clients that show the work (Telegram)."""

import json
import logging
import re
from typing import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from backend.chat.actions import CARD_PREFIX, action_tools
from backend.auth.store import UserStore
from backend.chat.media import media_tools
from backend.chat.context import build_snapshot, format_profile, format_snapshot
from backend.chat.tools import read_tools
from backend.llm import llm_failed, llm_service
from backend.profile.store import ProfileStore
from backend.prompts import render, shared_text

logger = logging.getLogger(__name__)

# The socket forwards whatever history the browser holds; bound what reaches the model.
MAX_HISTORY_TURNS = 20
MAX_TURN_CHARS = 4000
# Graph steps for one reply: 6 model calls and the tool rounds between them (LangGraph counts both).
RECURSION_LIMIT = 12
OUT_OF_STEPS = "That needed more lookups than one reply allows. Ask about one part of it."

# Tools sent with every message are paid for on every model step, so only the likely ones go.
_CORE_TOOLS = {"get_portfolio", "query_my_data", "search_news", "price_summary", "resolve_symbol_tool",
               "fetch_stock_info_tool", "next_results", "get_market_backdrop"}
_INTENT_TOOLS = (
    (re.compile(r"journal|habit|trades?\b|p&l|pnl|mistake|revenge", re.I), {"get_journal"}),
    (re.compile(r"paper|engine|autopilot|\brun\b|rotation|ai account", re.I), {"get_paper"}),
    (re.compile(r"proposal|pending|decision|idea|suggestion|approve|decline", re.I), {"get_decisions"}),
    (re.compile(r"limit|guardrail|kill.?switch|cap\b", re.I), {"get_limits"}),
    (re.compile(r"learn|what.*(engine|ai).*(found|changed)", re.I), {"get_learning"}),
    (re.compile(r"strateg", re.I), {"get_strategy_library", "get_built_strategies"}),
    (re.compile(r"index|nifty|sensex|bank nifty|\^NSE", re.I), {"explain_index"}),
    (re.compile(r"history|chart|trend|since|year|month", re.I), {"fetch_price_history_tool"}),
    (re.compile(r"chart|graph|plot|draw|image|picture|visual", re.I), {"make_chart", "generate_image"}),
)
_PAGE_TOOLS = (("journal", {"get_journal"}), ("ai", {"get_paper", "get_decisions"}), ("pick", {"get_decisions"}),
               ("strateg", {"get_strategy_library", "get_built_strategies"}), ("lab", {"get_learning"}))
# Any of these, in the message or the last exchange ("yes, do it"), brings the propose_ tools.
_ACTION_WORDS = re.compile(
    r"\b(buy|sell|order|exit|cancel|modify|approve|decline|reject|stop|start|set|change|raise|lower|increase|reduce|"
    r"remember|save|create|build|trim|add|place|confirm|yes|do it|go ahead|ok|okay)\b", re.I)


def pick_tools(tools: list, message: str, history: list, page: str) -> list:
    """The tools this message is likely to need. A propose_ tool only prepares a card, so a miss costs a
    rephrase, never a wrong order; widen the patterns if the usage ledger shows rephrasing."""
    recent = " ".join(str(t.get("content", "")) for t in (history or [])[-2:] if isinstance(t, dict))[-2000:]
    wanted = set(_CORE_TOOLS)
    for pattern, names in _INTENT_TOOLS:
        if pattern.search(message):
            wanted |= names
    for word, names in _PAGE_TOOLS:
        if word in (page or "").lower():
            wanted |= names
    act = bool(_ACTION_WORDS.search(f"{message} {recent}"))
    return [t for t in tools if t.name in wanted or (act and t.name.startswith("propose_"))]

TOOL_LABELS = {
    "get_portfolio": "Reading your portfolio", "get_journal": "Reading your journal",
    "get_paper": "Checking the paper engine", "get_decisions": "Reading your proposals",
    "get_limits": "Reading your limits", "explain_index": "Explaining the index",
    "query_my_data": "Looking through your data", "propose_memory": "Preparing a memory",
    "propose_approve": "Preparing an approval", "propose_decline": "Preparing a decline",
    "propose_paper_run": "Preparing a paper-run change", "propose_setting": "Preparing a settings change",
    "propose_order": "Preparing an order", "propose_exit": "Preparing an exit",
    "propose_cancel_order": "Preparing a cancellation", "propose_modify_order": "Preparing an order change",
    "propose_stop_loss": "Preparing a stop-loss", "propose_strategy": "Preparing a strategy",
    "get_learning": "Reading what the engine learned", "get_strategy_library": "Reading the strategy library",
    "get_built_strategies": "Reading your strategies", "search_news": "Searching the news",
    "get_market_backdrop": "Reading the market backdrop", "fetch_stock_info_tool": "Looking up the company",
    "fetch_price_history_tool": "Reading the price history", "resolve_symbol_tool": "Finding the symbol",
    "make_chart": "Drawing a chart", "generate_image": "Generating an image",
    "price_summary": "Reading the price trend", "next_results": "Checking results dates",
}


def _text(content) -> str:
    if isinstance(content, list):  # some providers stream parts
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content or "")


def _questions(text: str) -> list[str]:
    """Up to three one-line suggestions from the model's reply, with any list
    numbering or bullets it added anyway stripped off. Replies ("Yes, approve
    it") count as much as questions; a preamble line ending in ':' does not."""
    lines = (line.strip().lstrip("-*•0123456789.) ").strip().strip('"') for line in text.splitlines())
    return [line for line in lines if line and not line.endswith(":") and len(line) <= 90][:3]


# The model appends its suggested next messages after this line, in the same
# call as the answer (prompts/chat.md); the stream never shows it.
NEXT_MARKER = "<<<NEXT>>>"


class _Trailer:
    """Splits the streamed reply from what follows NEXT_MARKER, holding back
    any tail that could be the start of the marker until it is decided."""

    def __init__(self):
        self.held, self.trailer = "", None

    def feed(self, text: str) -> str:
        if self.trailer is not None:
            self.trailer += text
            return ""
        self.held += text
        if NEXT_MARKER in self.held:
            before, _, after = self.held.partition(NEXT_MARKER)
            self.held, self.trailer = "", after
            return before
        keep = max((n for n in range(1, len(NEXT_MARKER)) if self.held.endswith(NEXT_MARKER[:n])), default=0)
        out, self.held = self.held[:len(self.held) - keep], self.held[len(self.held) - keep:]
        return out

    def flush(self) -> str:
        """Text held back, released (a tool call or the end of the reply).
        A marker seen before a tool call was premature: forget its trailer."""
        out, self.held, self.trailer = self.held, "", None
        return out


async def suggest_followups(question: str, answer: str) -> list[str]:
    """Next questions worth one tap. Best-effort: any failure means no chips,
    never a broken reply."""
    try:
        system, prompt = render("chat_followups", question=question, answer=answer[-2000:])
        reply = await llm_service.get_completion(prompt, system_prompt=system, task="chat.followups")
        # get_completion reports failure in-band; never show that as a chip.
        if not reply or llm_failed(reply):
            return []
        return _questions(reply)
    except Exception as exc:
        logger.warning("chat follow-ups failed: %s", exc)
        return []


async def _profile(db, user_id: str) -> str:
    """Never fails the answer: an unreadable profile is reported as such."""
    try:
        user = await UserStore(db).get_by_id(user_id)
        return format_profile(user.name if user else "the trader", await ProfileStore(db).get(user_id))
    except Exception as exc:
        logger.warning("chat profile unavailable for %s: %s", user_id, exc)
        return "profile: unavailable"


async def stream_chat(db, redis, user_id: str, message: str, history: list, context: dict,
                      media: bool = False) -> AsyncIterator[dict]:
    """media=True adds make_chart and generate_image, whose chart/image events only the web widget draws."""
    llm = await llm_service.get_llm(task="chat.answer")
    if not llm:
        yield {"type": "content", "data": "The AI service is not available right now."}
        return

    snapshot = await build_snapshot(db, redis, user_id)
    from backend.portfolio.digest import verdicts_visible

    # The same audience as the Portfolio page's verdicts: a personal call needs registration for anyone else.
    view = shared_text("chat_view_owner" if await verdicts_visible(db, user_id) else "chat_view_user")
    system, page_note = render("chat", snapshot=format_snapshot(snapshot), profile=await _profile(db, user_id), view=view,
                               page=(context or {}).get("page") or "unknown")
    if (context or {}).get("symbol"):
        page_note += f" (looking at {context['symbol']})"
    messages = [SystemMessage(content=f"{system}\n\n{page_note}")]
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        if not isinstance(turn, dict):
            continue
        content = str(turn.get("content", ""))[:MAX_TURN_CHARS]
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=content))
        elif turn.get("role") == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=message))

    shown: list[dict] = []  # chart/image events the media tools queue
    tools = read_tools(db, redis, user_id) + action_tools(db, redis, user_id, message)
    all_tools = tools + (media_tools(shown) if media else [])
    agent = create_react_agent(llm, pick_tools(all_tools, message, history, (context or {}).get("page") or ""))
    answer = ""
    split = _Trailer()
    suggestions: list[str] = []
    carded = False
    try:
        async for event in agent.astream_events({"messages": messages}, {"recursion_limit": RECURSION_LIMIT}, version="v1"):
            kind = event["event"]
            name = event.get("name", "")
            label = TOOL_LABELS.get(name, f"Using {name}")
            if kind == "on_tool_start":
                if held := split.flush():
                    yield {"type": "content", "data": held}
                answer = ""  # text before a tool call is narration; follow-ups track the final reply
                yield {"type": "thinking", "data": label + "…"}
                yield {"type": "step", "data": {"id": event.get("run_id"), "phase": "start", "label": label,
                                                "input": event["data"].get("input")}}
            elif kind == "on_tool_end":
                yield {"type": "step", "data": {"id": event.get("run_id"), "phase": "end", "label": label}}
                output = event["data"].get("output")
                text = getattr(output, "content", output)
                if isinstance(text, str) and text.startswith(CARD_PREFIX):
                    carded = True
                    yield {"type": "action", "data": json.loads(text[len(CARD_PREFIX):])}
                while shown:
                    yield shown.pop(0)
            elif kind == "on_chat_model_stream":
                # A tool that calls a model itself (symbol lookup, peers) streams too: that is not the reply.
                if (event.get("metadata") or {}).get("langgraph_node") == "tools":
                    continue
                text = split.feed(_text(event["data"]["chunk"].content))
                if text:
                    answer += text
                    yield {"type": "content", "data": text}
    except Exception as exc:
        logger.error("chat agent failed for %s: %s", user_id, exc)
        yield {"type": "content", "data": "Something went wrong answering that; try again in a minute."}
        return

    if not answer and not carded and split.trailer is None and not split.held:
        answer = OUT_OF_STEPS  # LangGraph ends on a canned message it does not stream
        yield {"type": "content", "data": answer}
    if split.trailer is not None:
        suggestions = _questions(split.trailer)
    elif held := split.flush():
        answer += held
        yield {"type": "content", "data": held}
    # The reply is complete; clients may show it now rather than wait on the
    # fallback call below (Telegram sends its final message here).
    yield {"type": "answer_end", "data": None}
    # One call normally: the answer carried its suggestions. The separate
    # follow-up call is only a fallback for when the model left them out.
    if not suggestions and answer:
        suggestions = await suggest_followups(message, answer)
    if suggestions:
        yield {"type": "suggestions", "data": suggestions}
