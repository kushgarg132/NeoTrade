"""Every LLM call site says which tier it runs on, so a new one cannot
silently land on the most expensive model."""

import re
from pathlib import Path

BACKEND = Path(__file__).parents[1]
EXPECTED = {
    "components/analyst/agent.py": ["deep", "standard"],   # news scoring feeds trade scores; report
    "datalayer/news.py": ["fast", "deep"],
    "datalayer/market.py": ["standard"],                 # the market brief                # triage; impacts feed trade scores
    "plan/builder.py": ["deep", "deep"],                  # the per-user game plan (single call; tool loop)
    "plan/revise.py": [],                                 # revisions call builder._llm (deep)
    "components/master/search.py": ["deep"],                # Indian peers came out wrong on Flash
    "instruments/resolve.py": ["fast"],
    "research/index_move.py": ["standard"],
    "portfolio/review.py": ["deep"],
    "learning/report.py": ["standard"],
    "learning/hypotheses.py": ["deep"],
    "chat/agent.py": ["fast", "deep"],                   # follow-up chips; the reply
}


def test_every_llm_call_names_its_tier():
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        # llm.py and ai/runner.py pass their caller's tier through; the callers are checked.
        if rel.startswith("tests/") or rel in ("llm.py", "routers/settings.py", "ai/runner.py"):
            continue
        text = path.read_text()
        calls = re.findall(r"await [\w.]*(?:get_completion|get_llm|run_with_tools)\((.*?)\)", text, flags=re.S)
        if not calls:
            continue
        tiers = [m.group(1) for c in calls if (m := re.search(r'tier="(\w+)"', c))]
        assert len(tiers) == len(calls), f"{rel}: an LLM call without tier="
        assert tiers == EXPECTED.get(rel), f"{rel}: tiers {tiers}"
