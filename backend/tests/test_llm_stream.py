"""LLMService.stream_completion: text deltas, one charge, fallback only before the first chunk."""

import pytest

from backend import llm as llm_module
from backend.llm import LLMService


class _Chunk:
    def __init__(self, content):
        self.content = content


def _ev(content):
    return {"event": "on_chat_model_stream", "data": {"chunk": _Chunk(content)}}


class _Fake:
    def __init__(self, events, fail=False):
        self.events, self.fail = events, fail

    async def astream_events(self, *a, **k):
        for e in self.events:
            yield e
        if self.fail:
            raise RuntimeError("boom")

    async def ainvoke(self, messages):
        return _Chunk("whole answer")


@pytest.fixture
def svc(monkeypatch):
    async def no_note(*a, **k):
        return None

    monkeypatch.setattr(llm_module, "_note", no_note)
    s = LLMService()
    s.calls = 0
    return s


def _serve(svc, fake):
    async def get_llm(tier=None, feature=None):
        svc.calls += 1
        return fake

    svc.get_llm = get_llm


async def _collect(svc):
    return [d async for d in svc.stream_completion("p", "s")]


async def test_stream_yields_each_chunk(svc):
    _serve(svc, _Fake([_ev("Hel"), {"event": "on_chain_end", "data": {}}, _ev("lo")]))
    assert await _collect(svc) == ["Hel", "lo"]


async def test_failure_before_first_chunk_falls_back_to_get_completion(svc):
    _serve(svc, _Fake([], fail=True))
    assert await _collect(svc) == ["whole answer"]
    assert svc.calls == 1  # no second charge


async def test_failure_after_a_chunk_raises(svc):
    _serve(svc, _Fake([_ev("a")], fail=True))
    got = []
    with pytest.raises(RuntimeError):
        async for d in svc.stream_completion("p", "s"):
            got.append(d)
    assert got == ["a"]


async def test_disabled_feature_yields_llm_disabled(svc):
    _serve(svc, None)
    assert await _collect(svc) == ["LLM_DISABLED"]


async def test_content_block_chunks_are_joined_text(svc):
    _serve(svc, _Fake([_ev([{"text": "a"}, "b"])]))
    assert await _collect(svc) == ["ab"]
