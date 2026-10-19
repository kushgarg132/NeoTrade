"""Every LLM call site says which tier it runs on, so a new one cannot
silently land on the most expensive model, and which feature it serves, so
its tokens land on that feature's gateway key (Phase 17.2.5)."""

import re
from pathlib import Path

BACKEND = Path(__file__).parents[1]
EXPECTED = {
    "ai/analyst.py": ["deep", "standard"],   # news scoring feeds trade scores; report
    "datalayer/news.py": ["fast", "deep"],
    "datalayer/market.py": ["standard"],                 # the market brief                # triage; impacts feed trade scores
    "plan/builder.py": ["deep", "deep"],                  # the per-user game plan (single call; tool loop)
    "plan/revise.py": ["deep"],                           # revisions: tool loop; single call via builder._llm
    "research/search.py": ["deep"],                # Indian peers came out wrong on Flash
    "instruments/resolve.py": ["fast"],
    "research/index_move.py": ["standard"],
    "portfolio/review.py": ["deep"],
    "learning/report.py": ["standard"],
    "learning/hypotheses.py": ["deep"],
    "builder/draft.py": ["deep"],                         # the weekly strategy drafts
    "chat/agent.py": ["fast", "deep"],                   # follow-up chips; the reply
    # AI summaries: summaries/core.py::produce makes the call, each generator names tier and feature to it
    "summaries/day.py": ["fast"], "summaries/holding.py": ["fast"], "summaries/activity.py": ["standard"],
    "summaries/weekly.py": ["standard"], "summaries/habits.py": ["standard"],
}

FEATURE = {
    "ai/analyst.py": "research", "research/search.py": "research",
    "instruments/resolve.py": "research", "research/index_move.py": "research",
    "datalayer/news.py": "news", "datalayer/market.py": "news",
    "plan/builder.py": "plan", "plan/revise.py": "plan",
    "portfolio/review.py": "portfolio", "chat/agent.py": "chat",
    "learning/report.py": "learning", "learning/hypotheses.py": "learning",
    "builder/draft.py": "learning",
    "summaries/day.py": "portfolio", "summaries/holding.py": "news", "summaries/activity.py": "plan",
    "summaries/weekly.py": "portfolio", "summaries/habits.py": "learning",
}


def test_every_llm_call_names_its_tier():
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        # llm.py, ai/runner.py and summaries/core.py pass their caller's tier through; the callers are checked.
        if rel.startswith("tests/") or rel in ("llm.py", "routers/settings.py", "ai/runner.py", "summaries/core.py"):
            continue
        text = path.read_text()
        calls = re.findall(r"await [\w.]*(?:get_completion|get_llm|run_with_tools|produce)\((.*?)\)", text, flags=re.S)
        if not calls:
            continue
        tiers = [m.group(1) for c in calls if (m := re.search(r'tier="(\w+)"', c))]
        assert len(tiers) == len(calls), f"{rel}: an LLM call without tier="
        assert tiers == EXPECTED.get(rel), f"{rel}: tiers {tiers}"
        features = {m.group(1) for c in calls if (m := re.search(r'feature="(\w+)"', c))}
        assert features == {FEATURE[rel]} and all("feature=" in c for c in calls), f"{rel}: features {features}"


def test_a_feature_with_its_own_key_never_spills_onto_the_shared_one(monkeypatch):
    # The key's daily budget in OmniRoute is the feature's budget: falling
    # back to the shared key on a 429 would make it meaningless.
    from backend.llm import LLMService

    service = LLMService()
    monkeypatch.setattr(service, "keys", ["shared"])
    monkeypatch.setattr(service, "feature_keys", {"news": "news-key"})
    assert service.keys_for("news") == ["news-key"]
    assert service.keys_for("chat") == ["shared"] and service.keys_for(None) == ["shared"]
