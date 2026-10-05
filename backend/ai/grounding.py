"""Every figure an AI states must come from the data it was given.

A figure is a ₹ amount, a percentage, a decimal, or a bare integer of four
or more digits (not a year). Dates, times, years, list markers, x/y scores
and small bare counts ("3 names", "20 days") are not figures. A figure is
supported when some number in the call's facts is within 0.5% of it, or --
for a percentage -- within half a unit of its last shown digit (2.3% matches
2.347; 2% does not match 2.9). Unsupported figures get one retry; whatever is still unsupported
has its sentence dropped."""

import re
from typing import Awaitable, Callable, Optional

REL_TOLERANCE = 0.005
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b"
                   r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b|\b\d{1,2}:\d{2}\b",
                   re.IGNORECASE)
# Comma groups of 2-3 digits (Indian 1,00,000 and western 100,000), never a trailing comma.
_NUMBER = re.compile(r"(?<![\w/.])(₹\s?)?([-−+]?\d+(?:,\d{2,3})*(?:\.\d+)?)(\s?%)?(?![\w/])")
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def figures(text: str) -> list[tuple[str, float, int, bool]]:
    """(raw token, value, decimals shown, is_percent) for each figure in `text`."""
    text = _LIST_MARKER.sub(" ", _DATE.sub(" ", text))
    out = []
    for m in _NUMBER.finditer(text):
        rupee, number, percent = m.group(1), m.group(2), m.group(3)
        digits = number.replace(",", "").replace("−", "-")
        try:
            value = float(digits)
        except ValueError:
            continue
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        bare_int = not rupee and not percent and decimals == 0 and "," not in number
        if bare_int and (len(digits.lstrip("+-")) < 4 or 1900 <= value <= 2100):
            continue
        out.append((m.group(0).strip(), abs(value), decimals, bool(percent)))
    return out


def numbers_in(facts) -> list[float]:
    found: list[float] = []

    def walk(node):
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            found.append(abs(float(node)))
        elif isinstance(node, str):
            try:
                found.append(abs(float(node.replace(",", ""))))
            except ValueError:
                pass
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
    walk(facts)
    return found


def _supported(value: float, decimals: int, percent: bool, numbers: list[float]) -> bool:
    for x in numbers:
        if percent and abs(x - value) <= 0.5 * 10 ** (-decimals):  # what rounding to the shown digit allows
            return True
        if abs(x - value) <= REL_TOLERANCE * max(abs(x), abs(value), 1e-9):
            return True
    return False


def unsupported(text: str, facts) -> list[str]:
    numbers = numbers_in(facts)
    return [raw for raw, value, decimals, percent in figures(text) if not _supported(value, decimals, percent, numbers)]


def _contains(sentence: str, token: str) -> bool:
    """The token as a whole figure, not inside a longer one (2.3% is not in 12.3%)."""
    return re.search(r"(?<![\w.,])" + re.escape(token) + r"(?![\w,]|\.\d)", sentence) is not None


def strip_unsupported(text: str, tokens: list[str]) -> str:
    """Drops each sentence holding an unsupported figure, line by line, so
    lists and paragraphs survive; a list item left empty goes too."""
    if not tokens:
        return text
    lines = []
    for line in text.split("\n"):
        marker = _LIST_MARKER.match(line + " ")
        prefix, body = ((line + " ")[:marker.end()], (line + " ")[marker.end():]) if marker else ("", line)
        kept = [s for s in _SENTENCE.split(body.strip()) if s and not any(_contains(s, t) for t in tokens)]
        if not kept and body.strip():
            continue  # the whole line (or list item) was unsupported
        lines.append((prefix + " ".join(kept)).rstrip() if kept else line)
    return "\n".join(lines).strip()


async def grounded(text: str, facts, retry: Optional[Callable[[list[str]], Awaitable[str]]]) -> tuple[str, bool]:
    """(text safe to show, whether it was grounded as written)."""
    bad = unsupported(text, facts)
    if not bad:
        return text, True
    if retry is not None:
        text = await retry(bad)
        bad = unsupported(text, facts)
        if not bad:
            return text, True
    return strip_unsupported(text, bad), False
