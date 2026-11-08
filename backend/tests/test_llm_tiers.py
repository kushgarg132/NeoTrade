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


_CALL = {"id": "call_1", "type": "function", "function": {"name": "step_one", "arguments": "{}"},
         "extra_content": {"google": {"thought_signature": "sig-1"}}}


def _next_request(chat, ai_message):
    from langchain_core.messages import HumanMessage, ToolMessage

    messages = [HumanMessage("q"), ai_message, ToolMessage("result", tool_call_id="call_1")]
    return chat._get_request_payload(messages)["messages"][1]


def _gemini():
    from backend.gemini_chat import GeminiChat

    return GeminiChat(model="gemini-3.5-flash", api_key="k", base_url="http://unused")


def test_gemini_sends_back_the_signature_of_a_plain_tool_call():
    chat = _gemini()
    raw = {"id": "r", "model": "m", "object": "chat.completion", "created": 1, "choices": [
        {"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "tool_calls": [_CALL]}}]}
    ai = chat._create_chat_result(raw).generations[0].message
    assert _next_request(chat, ai)["tool_calls"][0]["extra_content"] == _CALL["extra_content"]


def test_gemini_sends_back_the_signature_of_a_streamed_tool_call():
    from langchain_core.messages import AIMessageChunk

    chat = _gemini()
    raw = {"id": "r", "model": "m", "object": "chat.completion.chunk", "created": 1, "choices": [
        {"index": 0, "delta": {"role": "assistant", "tool_calls": [{**_CALL, "index": 0}]}}]}
    ai = chat._convert_chunk_to_generation_chunk(raw, AIMessageChunk, {}).message
    assert _next_request(chat, ai)["tool_calls"][0]["extra_content"] == _CALL["extra_content"]


async def test_google_models_get_the_signature_keeping_client(monkeypatch):
    from backend.gemini_chat import GeminiChat

    async def fake_current(db=None, tier=None):
        return "google/gemini-3.5-flash"

    monkeypatch.setattr(llm_module, "current_llm_model", fake_current)
    monkeypatch.setattr(llm_module.settings, "GEMINI_API_KEY", "g-key")
    assert isinstance(await LLMService().get_llm(), GeminiChat)
