"""Every LLM prompt this backend sends lives as a Markdown file in this
directory, so a prompt can be read and edited as text, not hunted for
inside f-strings.

File format:

    ---
    version: 2
    system: The system prompt for this call. Lines after the first belong
      to it too.
    ---
    The user prompt, with {{placeholders}} for values.

`version` is optional (1 when absent): bump it when the wording changes, so
stored output can be traced to the prompt that wrote it (`prompt_id`).
`{{> name}}` pastes shared/name.md, in the system prompt or the body, so a rule
several prompts share lives once.

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
_PART = re.compile(r"\{\{>\s*(\w+)\s*\}\}")


@lru_cache(maxsize=None)
def _load(name: str) -> tuple[str, str, int]:
    text = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"prompts/{name}.md must start with a --- front-matter block")
    text = _PART.sub(lambda m: (_DIR / "shared" / f"{m.group(1)}.md").read_text(encoding="utf-8").strip(), text)
    front, body = text[4:].split("\n---\n", 1)
    system, version = [], 1
    for line in front.splitlines():
        if line.startswith("version:"):
            version = int(line.partition(":")[2])
        elif line.startswith("system:"):
            system.append(line.partition(":")[2].strip())
        elif system:
            system.append(line.strip())
    if not system or not system[0]:
        raise ValueError(f"prompts/{name}.md has no `system:` line")
    return "\n".join(system), body.strip(), version


def prompt_id(name: str) -> str:
    """`name@version`, stored beside what the prompt wrote."""
    return f"{name}@{_load(name)[2]}"


def render(name: str, /, **values) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for prompts/<name>.md. `name`
    is positional-only so a prompt may use a {{name}} placeholder itself."""
    system, body, _ = _load(name)
    wanted = set(_PLACEHOLDER.findall(body))
    if missing := wanted - values.keys():
        raise KeyError(f"prompts/{name}.md needs values for {sorted(missing)}")
    if extra := values.keys() - wanted:
        raise KeyError(f"prompts/{name}.md has no placeholder for {sorted(extra)}")
    return system, _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), body)
