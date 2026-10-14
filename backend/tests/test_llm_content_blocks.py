from types import SimpleNamespace

import pytest

from backend.llm import llm_service


@pytest.mark.asyncio
async def test_content_blocks_come_back_as_one_string(monkeypatch):
    # codex models answer in content blocks; callers expect text (news_process crash, 2026-10-14).
    class _Llm:
        async def ainvoke(self, messages):
            return SimpleNamespace(content=[{"type": "text", "text": '{"a": '}, {"type": "text", "text": "1}"}])

    async def get_llm(**_):
        return _Llm()

    monkeypatch.setattr(llm_service, "get_llm", get_llm)
    assert await llm_service.get_completion("p", system_prompt="s") == '{"a": 1}'
