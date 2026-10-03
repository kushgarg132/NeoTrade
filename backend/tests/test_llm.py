"""backend/llm.py: the per-user model override (use_model) and how
get_llm() picks a model -- the override first if one is set for the current
task, the deployment default (backend.app_settings.current_llm_model)
otherwise.
"""

import asyncio

import pytest

from backend import llm as llm_module
from backend.llm import LLMService, use_model


class _FakeChatOpenAI:
    def __init__(self, model, **kwargs):
        self.model = model

    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)
    svc = LLMService()
    svc.keys = ["k1"]
    return svc


@pytest.fixture(autouse=True)
def _default_model(monkeypatch):
    async def fake_current_llm_model(tier=None):
        return "deployment/default"

    monkeypatch.setattr(llm_module, "current_llm_model", fake_current_llm_model)


async def test_get_llm_uses_the_deployment_default_with_no_override(service):
    llm = await service.get_llm()
    assert llm.model == "deployment/default"


async def test_get_llm_uses_the_override_inside_a_with_block(service):
    with use_model("user/preferred-model"):
        llm = await service.get_llm()
    assert llm.model == "user/preferred-model"


async def test_get_llm_falls_back_outside_the_with_block(service):
    with use_model("user/preferred-model"):
        pass
    llm = await service.get_llm()
    assert llm.model == "deployment/default"


async def test_use_model_none_is_a_noop(service):
    with use_model(None):
        llm = await service.get_llm()
    assert llm.model == "deployment/default"


async def test_nested_use_model_restores_the_outer_value_on_exit(service):
    with use_model("outer/model"):
        with use_model("inner/model"):
            inner = await service.get_llm()
        after_inner = await service.get_llm()
    assert inner.model == "inner/model"
    assert after_inner.model == "outer/model"


async def test_override_set_in_a_parent_task_is_visible_in_a_child_task(service):
    """The mechanism analyze_sentiment_logic's per-article asyncio.gather
    fan-out relies on: a ContextVar set before create_task/gather is copied
    into the new Task's context at creation time, not shared live. This is
    the one test that would catch a wrong assumption about that
    propagation."""
    seen = {}

    async def child():
        seen["model"] = (await service.get_llm()).model

    with use_model("parent/model"):
        await asyncio.create_task(child())

    assert seen["model"] == "parent/model"
