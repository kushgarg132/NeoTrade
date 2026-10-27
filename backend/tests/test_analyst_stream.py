"""The report sink: stages and deltas reach whoever set it; without one nothing streams."""
import json
from unittest.mock import AsyncMock, MagicMock

from backend.ai import analyst
from backend.ai.analyst import AnalystAgent
from backend.datalayer import analysis
from backend.tests.test_analyst_agent import REPORT, SCORES, wired  # noqa: F401


def _stream(monkeypatch, chunks):
    async def gen(*a, **k):
        for c in chunks:
            yield c
    mock = MagicMock(side_effect=gen)
    monkeypatch.setattr(analyst.llm_service, "stream_completion", mock)
    return mock


async def test_with_a_sink_the_note_streams_and_joins_to_the_stored_text(wired, monkeypatch):
    llm, _ = wired
    llm.side_effect = [f"```json\n{json.dumps(SCORES)}\n```"]
    _stream(monkeypatch, [REPORT[:20], REPORT[20:]])
    events = []
    token = analyst.report_sink.set(events.append)
    try:
        out = await AnalystAgent().analyze({"symbol": "SBIN"})
    finally:
        analyst.report_sink.reset(token)
    assert events[0] == {"type": "stage", "step": "news", "count": 3}
    assert {"type": "stage", "step": "writing"} in events
    joined = "".join(e["text"] for e in events if e["type"] == "delta")
    assert joined == REPORT
    assert (out["summary"], out["thesis"]) == analyst._split_report(joined)


async def test_without_a_sink_one_get_completion_call_as_today(wired, monkeypatch):
    llm, _ = wired
    stream = _stream(monkeypatch, ["x"])
    await AnalystAgent().analyze({"symbol": "SBIN"})
    assert llm.await_count == 2
    stream.assert_not_called()


async def test_a_failing_stream_gives_the_unable_note(wired, monkeypatch):
    async def boom(*a, **k):
        yield "part"
        raise RuntimeError("down")
    monkeypatch.setattr(analyst.llm_service, "stream_completion", boom)
    token = analyst.report_sink.set(lambda e: None)
    try:
        got = await analyst._report(symbol="SBIN", sentiment_score="0", relevant_count=0, news="", events="[]")
    finally:
        analyst.report_sink.reset(token)
    assert got == ("Unable to generate summary.", "")


async def test_layer_build_sends_the_writing_stage(monkeypatch):
    monkeypatch.setattr(analyst, "_report", AsyncMock(return_value=("s", "t")))
    events = []
    token = analyst.report_sink.set(events.append)
    try:
        await analysis._build("SBIN", [], 0.0, None, MagicMock(get=AsyncMock(return_value=None)))
    finally:
        analyst.report_sink.reset(token)
    assert events == [{"type": "stage", "step": "writing"}]


async def test_a_disabled_llm_marker_is_not_streamed(wired, monkeypatch):
    _stream(monkeypatch, ["LLM_DISABLED", "Error generating response: x"])
    events = []
    token = analyst.report_sink.set(events.append)
    try:
        await analyst._report(symbol="SBIN", sentiment_score="0", relevant_count=0, news="", events="[]")
    finally:
        analyst.report_sink.reset(token)
    assert [e for e in events if e["type"] == "delta"] == []
