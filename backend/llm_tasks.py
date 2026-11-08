"""Every kind of LLM call the app makes, and how it runs: one table instead of a
tier and a feature repeated at each call site.

tier: which admin-set model (app_settings.TIERS).
feature: whose budget and on/off switch it falls under.
effort: reasoning_effort sent to Google (thinking bills as output); None = the model's default.
json: ask the provider for a JSON object rather than hoping for one.
fallback: on a provider failure, try the gateway's model. Off for news: a scorer
that changes mid-day muddies the accuracy report, and the batch simply waits."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Task:
    tier: str
    feature: str
    effort: Optional[str] = None
    json: bool = False
    fallback: bool = True


TASKS = {
    "news.triage": Task("fast", "news", json=True, fallback=False),
    "news.score": Task("standard", "news", effort="low", json=True, fallback=False),
    "news.filing": Task("standard", "news", json=True, fallback=False),
    "news.brief": Task("standard", "news", fallback=False),
    "research.analyst_score": Task("deep", "research"),
    "research.report": Task("standard", "research"),
    "research.peers": Task("deep", "research"),  # Indian peers came out wrong on Flash
    "research.resolve": Task("fast", "research"),
    "research.index_move": Task("standard", "research"),
    "portfolio.review": Task("deep", "portfolio"),
    "portfolio.rebalance": Task("deep", "portfolio"),
    "learning.report": Task("standard", "learning"),
    "learning.hypotheses": Task("deep", "learning"),
    "learning.builder": Task("deep", "learning"),
    "chat.answer": Task("standard", "chat"),
    "chat.followups": Task("fast", "chat"),
    "summary.day": Task("fast", "portfolio"),
    "summary.holding": Task("fast", "news"),
    "summary.activity": Task("standard", "plan"),
    "summary.weekly": Task("standard", "portfolio"),
    "summary.habits": Task("standard", "learning"),
}
