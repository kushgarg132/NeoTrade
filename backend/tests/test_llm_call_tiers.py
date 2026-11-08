"""Every LLM call site names a row of llm_tasks.TASKS, so a new one cannot silently
land on the most expensive model, and the table itself is pinned here."""

import re
from pathlib import Path

from backend.llm_tasks import TASKS

BACKEND = Path(__file__).parents[1]
EXPECTED = {
    "ai/analyst.py": {"research.analyst_score", "research.report"},
    "datalayer/news.py": {"news.triage", "news.score"},
    "datalayer/filings.py": {"news.filing"},
    "datalayer/market.py": {"news.brief"},
    "research/search.py": {"research.peers"},
    "instruments/resolve.py": {"research.resolve"},
    "research/index_move.py": {"research.index_move"},
    "portfolio/review.py": {"portfolio.review"},
    "portfolio/ai_rebalance.py": {"portfolio.rebalance"},
    "learning/report.py": {"learning.report"},
    "learning/hypotheses.py": {"learning.hypotheses"},
    "builder/draft.py": {"learning.builder"},
    "chat/agent.py": {"chat.followups", "chat.answer"},
    "summaries/day.py": {"summary.day"}, "summaries/holding.py": {"summary.holding"},
    "summaries/activity.py": {"summary.activity"}, "summaries/weekly.py": {"summary.weekly"},
    "summaries/habits.py": {"summary.habits"},
}


def test_every_llm_call_names_a_known_task():
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        # llm.py and summaries/core.py pass their caller's task through; the callers are checked.
        if rel.startswith("tests/") or rel in ("llm.py", "routers/settings.py", "summaries/core.py"):
            continue
        text = path.read_text()
        calls = re.findall(r"await [\w.]*(?:get_completion|get_llm|produce)\((.*?)\)", text, flags=re.S)
        if not calls:
            continue
        tasks = [m.group(1) for c in calls if (m := re.search(r'task="([\w.]+)"', c))]
        assert len(tasks) == len(calls), f"{rel}: an LLM call without task="
        assert set(tasks) == EXPECTED.get(rel), f"{rel}: tasks {tasks}"
        assert set(tasks) <= set(TASKS)


def test_news_never_falls_back_to_another_scorer():
    assert not any(t.fallback for name, t in TASKS.items() if name.startswith("news."))


def test_a_feature_with_its_own_key_never_spills_onto_the_shared_one(monkeypatch):
    # The key's daily budget in OmniRoute is the feature's budget: falling
    # back to the shared key on a 429 would make it meaningless.
    from backend.llm import LLMService

    service = LLMService()
    monkeypatch.setattr(service, "keys", ["shared"])
    monkeypatch.setattr(service, "feature_keys", {"news": "news-key"})
    assert service.keys_for("news") == ["news-key"]
    assert service.keys_for("chat") == ["shared"] and service.keys_for(None) == ["shared"]
