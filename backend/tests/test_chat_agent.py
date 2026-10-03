"""The chat agent: the user's snapshot and page ride in the system prompt,
and an action tool's card comes out as its own event."""

from langchain_core.messages import SystemMessage
from mongomock_motor import AsyncMongoMockClient

from backend.chat import agent


class _FakeAgent:
    def __init__(self, seen):
        self.seen = seen

    async def astream_events(self, payload, version):
        self.seen["messages"] = payload["messages"]
        yield {"event": "on_tool_start", "name": "propose_approve", "data": {}}
        yield {"event": "on_tool_end", "name": "propose_approve",
               "data": {"output": 'ACTION_CARD:{"id": "a1", "summary": "Approve SJVN"}'}}
        chunk = type("C", (), {"content": "Card ready."})()
        yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}}


async def _run(monkeypatch, seen):
    async def fake_llm(tier=None):
        return object()

    async def fake_snapshot(db, redis, user_id, now=None):
        seen["snapshot_user"] = user_id
        return {"market": {"session_open": False}}

    monkeypatch.setattr(agent.llm_service, "get_llm", fake_llm)
    monkeypatch.setattr(agent, "build_snapshot", fake_snapshot)
    monkeypatch.setattr(agent, "create_react_agent", lambda llm, tools: _FakeAgent(seen))
    db = AsyncMongoMockClient()["test_db"]
    return [e async for e in agent.stream_chat(db, None, "alice", "approve sjvn", [], {"page": "/portfolio"})]


async def test_stream_turns_an_action_tool_result_into_an_action_event(monkeypatch):
    events = await _run(monkeypatch, {})
    assert {"type": "action", "data": {"id": "a1", "summary": "Approve SJVN"}} in events
    assert events[-1] == {"type": "content", "data": "Card ready."}


async def test_system_prompt_carries_snapshot_and_page(monkeypatch):
    seen = {}
    await _run(monkeypatch, seen)
    first = seen["messages"][0]
    assert isinstance(first, SystemMessage)
    assert "session_open=False" in first.content and "/portfolio" in first.content
    assert seen["snapshot_user"] == "alice"


async def test_a_finished_reply_ends_with_follow_up_questions(monkeypatch):
    async def fake_completion(prompt, system_prompt, tier=None):
        assert tier == "fast" and "Card ready." in prompt
        return "1. Why SJVN?\n- What else is pending?\nnot a question\n\"How much is at risk?\"\nOne more?"

    monkeypatch.setattr(agent.llm_service, "get_completion", fake_completion)
    events = await _run(monkeypatch, {})
    assert events[-1] == {
        "type": "suggestions",
        "data": ["Why SJVN?", "What else is pending?", "How much is at risk?"],
    }


async def test_a_follow_up_failure_still_leaves_the_reply(monkeypatch):
    async def broken(prompt, system_prompt, tier=None):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(agent.llm_service, "get_completion", broken)
    events = await _run(monkeypatch, {})
    assert events[-1] == {"type": "content", "data": "Card ready."}
