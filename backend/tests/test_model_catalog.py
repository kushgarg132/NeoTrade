"""The model picker's Family -> Model -> Version tree, built from the
gateway's own model list (ids taken from the real OmniRoute catalog)."""

from backend.model_catalog import build_catalog

TEXT = ["text"]
MODELS = [
    {"id": "auto/claude-opus", "output_modalities": TEXT},
    {"id": "auto/best-free", "output_modalities": TEXT},
    {"id": "agy/claude-opus-4-6-thinking-high", "output_modalities": TEXT},
    {"id": "agy/claude-opus-4-6-thinking", "output_modalities": TEXT},
    {"id": "agy/claude-sonnet-4-6", "output_modalities": TEXT},
    {"id": "kr/claude-sonnet-5", "output_modalities": TEXT},
    {"id": "no-think/agy/claude-sonnet-4-6", "output_modalities": TEXT},
    {"id": "agy/gemini-3-flash", "output_modalities": TEXT},
    {"id": "agy/gemini-3.8-flash-low", "output_modalities": TEXT},
    {"id": "agy/gemini-3.5-flash-lite", "output_modalities": TEXT},
    {"id": "agy/gemini-3.1-pro-high", "output_modalities": TEXT},
    {"id": "tr/gpt-5.4", "output_modalities": TEXT},
    {"id": "cfp/deepseek-ai/deepseek-v4-pro-0813", "output_modalities": None},
    {"id": "aihorde/2DN", "output_modalities": ["image"]},
    {"id": "nvidia/llama-3.2-nv-embedqa-1b-v1", "output_modalities": None},
    {"id": "Kimi Coding", "output_modalities": TEXT},
]


def _tree():
    return {f["key"]: f for f in build_catalog(MODELS)}


def _line(family, line):
    return next(l for l in _tree()[family]["lines"] if l["key"] == line)


def test_families_come_in_order_and_skip_image_embedding_and_unroutable_models():
    tree = build_catalog(MODELS)
    assert [f["key"] for f in tree] == ["auto", "claude", "gemini", "gpt", "deepseek"]
    ids = {m["id"] for f in tree for l in f["lines"] for m in l["models"]}
    assert "aihorde/2DN" not in ids and "nvidia/llama-3.2-nv-embedqa-1b-v1" not in ids and "Kimi Coding" not in ids


def test_claude_splits_into_lines_and_versions_newest_first():
    tree = _tree()
    assert [l["key"] for l in tree["claude"]["lines"]] == ["opus", "sonnet"]
    sonnet = _line("claude", "sonnet")["models"]
    assert [(m["version"], m["provider"]) for m in sonnet] == [("5", "kr"), ("4.6", "agy"), ("4.6", "no-think/agy")]
    opus = _line("claude", "opus")["models"]
    assert {m["variant"] for m in opus} == {"thinking · high", "thinking"}


def test_gemini_lines_tell_flash_lite_from_flash():
    tree = _tree()
    assert [l["key"] for l in tree["gemini"]["lines"]] == ["pro", "flash", "flash-lite"]
    assert [m["version"] for m in _line("gemini", "flash")["models"]] == ["3.8", "3"]
    assert _line("gemini", "flash")["models"][0]["variant"] == "low"


def test_auto_routes_and_line_less_families_have_one_line():
    tree = _tree()
    assert [m["label"] for m in tree["auto"]["lines"][0]["models"]] == ["Best free", "Claude opus"]
    assert len(tree["deepseek"]["lines"]) == 1 and tree["deepseek"]["lines"][0]["models"][0]["version"] == "4"
    assert tree["claude"]["count"] == 5


def test_fable_is_a_claude_line_and_gpt_splits_by_generation():
    tree = {f["key"]: f for f in build_catalog([
        {"id": "dva/claude-fable-5-1-high", "output_modalities": TEXT},
        {"id": "tr/gpt-5.4", "output_modalities": TEXT},
        {"id": "dva/gpt-5-6-sol-max", "output_modalities": TEXT},
        {"id": "cfp/openai/gpt-oss-120b", "output_modalities": TEXT},
        {"id": "nvidia/gpt-4o", "output_modalities": TEXT},
    ])}
    fable = tree["claude"]["lines"][0]
    assert (fable["key"], fable["models"][0]["version"], fable["models"][0]["variant"]) == ("fable", "5.1", "high")
    assert [l["label"] for l in tree["gpt"]["lines"]] == ["GPT-5", "GPT-4", "OSS"]
    assert [m["version"] for m in tree["gpt"]["lines"][0]["models"]] == ["5.6", "5.4"]
