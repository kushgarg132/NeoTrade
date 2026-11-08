"""Each task asks for a tier; the tier's model is used unless the user has
a personal model override, which still wins."""

from backend import llm as llm_module
from backend.llm import LLMService, use_model


async def _model_for(monkeypatch, tier, override=None):
    seen = {}

    async def fake_current(db=None, tier=None):
        return {"fast": "agy/gemini-3-flash"}.get(tier, "auto/claude-opus")

    class _Chat:
        def __init__(self, model, **kwargs):
            seen["model"] = model

    import langchain_openai
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Chat)
    monkeypatch.setattr(llm_module, "current_llm_model", fake_current)
    service = LLMService()
    service.keys = ["k"]
    with use_model(override):
        await service.get_llm(tier=tier)
    return seen["model"]


async def test_get_llm_uses_the_tier_model(monkeypatch):
    assert await _model_for(monkeypatch, "fast") == "agy/gemini-3-flash"
    assert await _model_for(monkeypatch, None) == "auto/claude-opus"


async def test_a_personal_override_still_wins(monkeypatch):
    assert await _model_for(monkeypatch, "fast", override="user/own") == "user/own"


def test_route_sends_google_ids_to_google_and_the_rest_to_the_gateway(monkeypatch):
    monkeypatch.setattr(llm_module.settings, "GEMINI_API_KEY", "g-key")
    assert llm_module.route("google/gemini-2.5-flash", ["gw"]) == (
        "gemini-2.5-flash", llm_module.settings.GEMINI_BASE_URL, ["g-key"])
    assert llm_module.route("cx/gpt-5", ["gw"]) == ("cx/gpt-5", llm_module.settings.OMNIROUTE_BASE_URL, ["gw"])


async def test_a_google_model_with_no_key_is_disabled_not_sent_to_the_gateway(monkeypatch):
    async def fake_current(db=None, tier=None):
        return "google/gemini-2.5-flash"

    monkeypatch.setattr(llm_module, "current_llm_model", fake_current)
    monkeypatch.setattr(llm_module.settings, "GEMINI_API_KEY", None)
    service = LLMService()
    service.keys = ["gw"]
    assert await service.get_llm() is None
