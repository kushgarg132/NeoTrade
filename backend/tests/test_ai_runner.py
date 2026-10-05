import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from backend.ai import runner
from backend.ai.facts import as_tools


class _Script:
    """A fake chat model: bind_tools returns itself; ainvoke pops scripted replies."""

    def __init__(self, *replies):
        self.replies, self.seen, self.bound = list(replies), [], 0

    def bind_tools(self, tools, **kw):
        self.bound += 1
        return self

    async def ainvoke(self, messages, *a, **kw):
        self.seen.append(list(messages))
        if not self.replies:
            raise AssertionError("model called more times than scripted")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _call(name, args, i=0):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{i}"}])


async def _sentiment_tools():
    from backend.tests.test_datalayer_news import FakeRedis

    redis = FakeRedis()
    await redis.set("sentiment:TCS", "0.4")
    return as_tools(None, redis, None, ["sentiment"])


async def test_runs_tools_then_answers():
    llm = _Script(_call("sentiment", {"symbol": "TCS"}), AIMessage(content="TCS news sentiment is 0.4."))
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=await _sentiment_tools(), tier="fast", llm=llm)
    assert out["output"] == "TCS news sentiment is 0.4." and out["rounds"] == 2
    assert out["tool_trace"][0]["tool"] == "sentiment" and out["facts"][0]["stock"] == 0.4


async def test_unknown_tool_and_bad_args_become_error_messages():
    llm = _Script(_call("nope", {}), _call("sentiment", {"wrong": 1}, 1), AIMessage(content="done"))
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=await _sentiment_tools(), tier="fast", llm=llm)
    assert out["output"] == "done" and [t["error"] is not None for t in out["tool_trace"]] == [True, True]
    assert "error" in json.loads(llm.seen[1][-1].content)


async def test_stops_after_max_rounds_with_a_forced_answer():
    llm = _Script(*[_call("sentiment", {"symbol": "TCS"}, i) for i in range(2)], AIMessage(content="final"))
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=await _sentiment_tools(), tier="fast",
                                      max_rounds=2, llm=llm)
    assert out["output"] == "final" and out["rounds"] == 3
    assert "no more tools" in llm.seen[-1][-1].content.lower()


async def test_budget_cut_forces_the_final_answer():
    grants = iter([True, False, True])  # tool round, refused round, the final turn

    async def reserve():
        return next(grants, False)
    llm = _Script(_call("sentiment", {"symbol": "TCS"}), AIMessage(content="from what I have"))
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=await _sentiment_tools(), tier="fast",
                                      reserve=reserve, llm=llm)
    assert out["output"] == "from what I have" and out["rounds"] == 2


class _Verdict(BaseModel):
    verdict: str
    score: float


async def test_schema_repair_then_none():
    good = _Script(AIMessage(content="not json"), AIMessage(content='{"verdict": "BUY", "score": 0.7}'))
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=[], tier="fast", schema=_Verdict, llm=good)
    assert out["output"] == _Verdict(verdict="BUY", score=0.7)
    bad = _Script(AIMessage(content="nope"), AIMessage(content="still nope"))
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=[], tier="fast", schema=_Verdict, llm=bad)
    assert out["output"] is None


async def test_provider_error_uses_the_fallback():
    async def fallback():
        return "single-call answer"
    llm = _Script(RuntimeError("gateway rejects tools"))
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=[], tier="fast", fallback=fallback, llm=llm)
    assert out["output"] == "single-call answer" and out["used_fallback"] is True


async def test_kill_switch_uses_the_fallback(monkeypatch):
    monkeypatch.setattr(runner.settings, "AI_TOOLS_ENABLED", False)

    async def fallback():
        return "single-call answer"
    llm = _Script()
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=[], tier="fast", fallback=fallback, llm=llm)
    assert out["output"] == "single-call answer" and llm.seen == []


class _StrictProvider(_Script):
    """Rejects tool history unless tools are bound (Anthropic/Gemini behaviour)."""

    def bind_tools(self, tools, **kw):
        bound = _Script.__new__(_Script)
        bound.replies, bound.seen, bound.bound = self.replies, self.seen, 1
        return bound

    async def ainvoke(self, messages, *a, **kw):
        if any(getattr(m, "tool_calls", None) for m in messages):
            raise RuntimeError("tool_use blocks without tools")
        return await super().ainvoke(messages)


async def test_forced_final_turn_keeps_tools_bound():
    llm = _StrictProvider(_call("sentiment", {"symbol": "TCS"}), AIMessage(content="final from facts"))
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=await _sentiment_tools(), tier="fast",
                                      max_rounds=1, llm=llm)
    assert out["output"] == "final from facts" and out["used_fallback"] is False and out["facts"]


async def test_repair_turn_never_repeats_the_assistant_message():
    llm = _Script(AIMessage(content="not json"), AIMessage(content='{"verdict": "SELL", "score": 0.2}'))
    await runner.run_with_tools("t", system="s", prompt="p", tools=[], tier="fast", schema=_Verdict, llm=llm)
    roles = [type(m).__name__ for m in llm.seen[-1]]
    assert all(not (a == b == "AIMessage") for a, b in zip(roles, roles[1:]))


async def test_no_budget_means_no_model_call_at_all():
    async def reserve():
        return False
    llm = _Script()
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=await _sentiment_tools(), tier="fast",
                                      reserve=reserve, llm=llm)
    assert out["output"] is None and llm.seen == []


async def test_final_and_repair_turns_are_reserved():
    grants = iter([True, False, False])  # tool round, refused round, refused final turn

    async def reserve():
        return next(grants, False)
    llm = _Script(_call("sentiment", {"symbol": "TCS"}))
    out = await runner.run_with_tools("t", system="s", prompt="p", tools=await _sentiment_tools(), tier="fast",
                                      reserve=reserve, llm=llm)
    assert out["output"] is None and len(llm.seen) == 1
