"""Chat media tools: a chart is validated before the widget sees it, and its
event leaves the agent right after the tool that queued it."""

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.chat import agent
from backend.chat.media import chart_spec, media_tools


def test_chart_spec_accepts_matching_series():
    spec = chart_spec("P&L", "area", ["2026-10-01", "2026-10-02"], [{"name": "AI", "values": [1.5, None]}], "₹")
    assert spec["series"] == [{"name": "AI", "values": [1.5, None]}] and spec["unit"] == "₹"


@pytest.mark.parametrize("labels,series,kind", [
    (["a", "b"], [{"name": "x", "values": [1]}], "line"),                              # length mismatch
    (["a"], [{"name": "x", "values": [1]}, {"name": "y", "values": [2]}], "pie"),      # pie with two series
    ([], [{"name": "x", "values": []}], "bar"),                                        # empty
])
def test_chart_spec_refuses_bad_shapes(labels, series, kind):
    with pytest.raises(ValueError):
        chart_spec("t", kind, labels, series)


async def test_make_chart_queues_an_event_and_refusals_queue_nothing():
    sink = []
    make_chart = next(t for t in media_tools(sink) if t.name == "make_chart")
    ok = await make_chart.ainvoke({"title": "t", "kind": "bar", "labels": ["a"], "series": [{"name": "x", "values": [3]}]})
    bad = await make_chart.ainvoke({"title": "t", "kind": "bar", "labels": ["a", "b"], "series": [{"name": "x", "values": [3]}]})
    assert "shown" in ok and bad.startswith("Chart refused") and [e["type"] for e in sink] == ["chart"]


async def test_stream_emits_queued_chart_after_its_tool(monkeypatch):
    class _Fake:
        def __init__(self, tools):
            self.tools = {t.name: t for t in tools}

        async def astream_events(self, payload, version):
            yield {"event": "on_tool_start", "name": "make_chart", "data": {}}
            await self.tools["make_chart"].ainvoke({"title": "t", "kind": "line", "labels": ["a"],
                                                    "series": [{"name": "x", "values": [1]}]})
            yield {"event": "on_tool_end", "name": "make_chart", "data": {"output": "shown"}}

    async def fake_llm(tier=None, feature=None):
        return object()

    async def fake_snapshot(db, redis, user_id, now=None):
        return {"market": {"session_open": False}}

    monkeypatch.setattr(agent.llm_service, "get_llm", fake_llm)
    monkeypatch.setattr(agent, "build_snapshot", fake_snapshot)
    monkeypatch.setattr(agent, "create_react_agent", lambda llm, tools: _Fake(tools))
    db = AsyncMongoMockClient()["test_db"]
    events = [e async for e in agent.stream_chat(db, None, "alice", "chart it", [], {"page": "/"}, media=True)]
    assert any(e["type"] == "chart" and e["data"]["kind"] == "line" for e in events)


@pytest.mark.parametrize("kind", ["line", "bar", "area", "pie"])
def test_render_png_draws_every_kind(kind):
    from backend.chat.media import render_png

    spec = chart_spec("Mix", kind, ["2026-10-01", "2026-10-02", "2026-10-03"],
                      [{"name": "A", "values": [1.0, None, 3.0]}] if kind == "pie" else
                      [{"name": "A", "values": [1.0, None, 3.0]}, {"name": "B", "values": [2.0, 2.5, -1.0]}], "₹")
    if kind == "pie":
        spec["series"][0]["values"] = [1.0, 2.0, 3.0]
    png = render_png(spec)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 2000
