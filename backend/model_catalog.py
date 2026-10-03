"""The gateway's model list as a Family -> Model line -> Version tree, for the
step-by-step model picker in Settings -> AI.

OmniRoute lists hundreds of ids from many sources ("agy/claude-opus-4-6-
thinking-high", "cfp/deepseek-ai/deepseek-v4-pro-0813", image and embedding
models, "no-think/..." twins). Only chat models are kept; each is placed by
its name, with the source provider and the leftover name parts (effort,
thinking, ...) shown as the variant. Pure: no I/O.
"""

import re

# Family key, label, words that identify it in a model name. Order is the
# picker's order; the first match wins.
FAMILIES = [
    ("claude", "Claude", ("claude",)),
    ("gemini", "Gemini", ("gemini",)),
    ("gpt", "GPT", ("gpt",)),
    ("deepseek", "DeepSeek", ("deepseek",)),
    ("qwen", "Qwen", ("qwen", "qwq")),
    ("glm", "GLM", ("glm",)),
    ("kimi", "Kimi", ("kimi",)),
    ("llama", "Llama", ("llama",)),
    ("grok", "Grok", ("grok",)),
    ("minimax", "MiniMax", ("minimax",)),
    ("gemma", "Gemma", ("gemma",)),
    ("mistral", "Mistral", ("mistral", "mixtral")),
]

# Model lines inside a family, checked in order (flash-lite before flash).
LINES = {
    "claude": [("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"), ("fable", "Fable")],
    "gemini": [("pro", "Pro"), ("flash", "Flash"), ("flash-lite", "Flash-Lite"), ("image", "Image")],
}
_LINE_MATCH_ORDER = {"gemini": ["image", "flash-lite", "flash", "pro"]}

_NOT_CHAT = re.compile(r"embed|rerank|retriev|guard|whisper|tts|ocr", re.I)
_VERSION = re.compile(r"(?<![a-z])v?(\d+(?:[.-]\d+)?)(?![\d])")


def _is_chat(model: dict) -> bool:
    if "/" not in model["id"]:
        return False  # not a routable provider/model id
    out = model.get("output_modalities")
    if out is not None:
        return "text" in out
    return not _NOT_CHAT.search(model["id"])


def _split(model_id: str) -> tuple[str, str]:
    """('no-think/agy', 'claude-sonnet-4-6') -- provider path and model name."""
    parts = model_id.split("/")
    if parts[0] == "no-think" and len(parts) > 2:
        return "/".join(parts[:2]), parts[-1]
    return parts[0], parts[-1]


def _family(name: str):
    lowered = name.lower()
    for key, label, words in FAMILIES:
        if any(word in lowered for word in words):
            return key, label
    return "other", "Other"


def _line(family: str, name: str):
    if family == "gpt":  # by generation: GPT-5, GPT-4, ...; open-weight ones apart
        if "gpt-oss" in name:
            return "oss", "OSS"
        generation = re.search(r"gpt-?(\d+)", name)
        return (f"gpt{generation.group(1)}", f"GPT-{generation.group(1)}") if generation else ("other", "Other")
    lines = LINES.get(family)
    if not lines:
        return "all", "All"
    labels = dict(lines)
    for key in _LINE_MATCH_ORDER.get(family, [k for k, _ in lines]):
        if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", name):
            return key, labels[key]
    return "other", "Other"


def _version(text: str) -> str:
    match = _VERSION.search(text)
    return match.group(1).replace("-", ".") if match else ""


def _version_key(version: str) -> tuple:
    return tuple(int(p) for p in version.split(".") if p.isdigit()) or (-1,)


def _entry(model_id: str, family: str) -> tuple[str, str, dict]:
    provider, name = _split(model_id)
    lowered = name.lower()
    line_key, line_label = _line(family, lowered)
    # The version is read after the line word ("claude-opus-4-6" -> 4.6) or,
    # without one, after the family word ("deepseek-v4-pro" -> 4).
    anchor = line_key if line_key in lowered else next(
        (w for w in dict((k, ws) for k, _, ws in FAMILIES).get(family, ()) if w in lowered), "")
    tail = lowered.split(anchor, 1)[1] if anchor and anchor in lowered else lowered
    version = _version(tail) or _version(lowered)
    rest = tail
    if version:
        pattern = "v?" + r"[.-]".join(re.escape(p) for p in version.split("."))
        rest = re.sub(pattern, "", rest, count=1)
    variant = " · ".join(p for p in re.split(r"[-_\s]+", rest) if p and p != "v")
    model = {"id": model_id, "provider": provider, "version": version, "variant": variant}
    return line_key, line_label, model


def build_catalog(models: list[dict]) -> list[dict]:
    families: dict[str, dict] = {}
    for model in models:
        if not _is_chat(model):
            continue
        provider, name = _split(model["id"])
        if provider == "auto":
            family = families.setdefault("auto", {"key": "auto", "label": "Auto (smart routing)", "lines": {}})
            line = family["lines"].setdefault("all", {"key": "all", "label": "Routes", "models": []})
            line["models"].append({
                "id": model["id"], "provider": "auto", "version": "", "variant": "",
                "label": name.replace("-", " ").replace(":", " · ").capitalize(),
            })
            continue
        key, label = _family(name)
        line_key, line_label, entry = _entry(model["id"], key)
        entry["label"] = name
        family = families.setdefault(key, {"key": key, "label": label, "lines": {}})
        line = family["lines"].setdefault(line_key, {"key": line_key, "label": line_label, "models": []})
        line["models"].append(entry)

    order = ["auto"] + [k for k, _, _ in FAMILIES] + ["other"]
    result = []
    for key in sorted(families, key=order.index):
        family = families[key]
        line_order = [k for k, _ in LINES.get(key, [])] + ["all", "oss", "other"]
        # GPT generations newest first, then the fixed lines.
        lines = sorted(family["lines"].values(), key=lambda l: (
            -int(l["key"][3:]) if re.fullmatch(r"gpt\d+", l["key"]) else 0,
            line_order.index(l["key"]) if l["key"] in line_order else len(line_order),
        ))
        for line in lines:
            if key == "auto":
                line["models"].sort(key=lambda m: m["label"])
            else:
                line["models"].sort(key=lambda m: (m["provider"], m["variant"]))
                line["models"].sort(key=lambda m: _version_key(m["version"]), reverse=True)  # stable: newest first
        result.append({
            "key": key, "label": family["label"], "count": sum(len(l["models"]) for l in lines), "lines": lines,
        })
    return result
