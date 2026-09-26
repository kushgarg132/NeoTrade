"""Every LLM prompt this backend sends lives as a Markdown file in this
directory, so a prompt can be read and edited as text, not hunted for
inside f-strings.

File format:

    ---
    system: One line: the system prompt for this call.
    ---
    The user prompt, with {{placeholders}} for values.

Placeholders are `{{name}}` rather than `{name}` so the JSON examples many
prompts include need no brace-escaping. `render` fails loudly on a
placeholder with no value or a value with no placeholder -- a silent typo
here would ship a prompt with a literal "{{symbol}}" in it.
"""

import re
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@lru_cache(maxsize=None)
def _load(name: str) -> tuple[str, str]:
    text = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"prompts/{name}.md must start with a --- front-matter block")
    front, body = text[4:].split("\n---\n", 1)
    system = ""
    for line in front.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "system":
            system = value.strip()
    if not system:
        raise ValueError(f"prompts/{name}.md has no `system:` line")
    return system, body.strip()


def render(name: str, /, **values) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for prompts/<name>.md. `name`
    is positional-only so a prompt may use a {{name}} placeholder itself."""
    system, body = _load(name)
    wanted = set(_PLACEHOLDER.findall(body))
    if missing := wanted - values.keys():
        raise KeyError(f"prompts/{name}.md needs values for {sorted(missing)}")
    if extra := values.keys() - wanted:
        raise KeyError(f"prompts/{name}.md has no placeholder for {sorted(extra)}")
    return system, _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), body)
