"""backend/suggestions/thesis.py: attaching an LLM-derived rationale to
fresh suggestions using the user's own saved model preference, if any.
"""

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.llm import _model_override
from backend.prefs import PrefsStore
from backend.suggestions.store import SuggestionStore
from backend.suggestions.thesis import attach_theses


def _mongo():
    return AsyncMongoMockClient()["test_db"]


class _Report:
    def __init__(self, thesis):
        self.thesis = thesis
        self.analyst_summary = ""


class _RecordingAgent:
    def __init__(self, thesis="Fine business."):
        self.thesis = thesis
        self.seen_models = []

    async def run(self, symbol):
        self.seen_models.append(_model_override.get())
        return _Report(self.thesis)


async def _seed_suggestion(mongo, user_id, suggestion_id, symbol):
    await mongo["suggestions"].insert_one({
        "id": suggestion_id, "user_id": user_id, "symbol": symbol, "mode": "LONGTERM",
        "status": "PENDING", "ai_thesis": None,
    })


async def test_attaches_a_thesis_using_the_users_preferred_model():
    mongo = _mongo()
    await _seed_suggestion(mongo, "alice", "s1", "RELIANCE")
    await PrefsStore(mongo).update("alice", {"omniroute_model": "user/preferred"})
    agent = _RecordingAgent()

    attached = await attach_theses(mongo, "alice", [{"id": "s1", "symbol": "RELIANCE"}], agent=agent)

    assert attached == 1
    assert agent.seen_models == ["user/preferred"]
    assert (await SuggestionStore(mongo).get("alice", "s1"))["ai_thesis"] == "Fine business."


async def test_no_saved_preference_is_a_noop_override():
    mongo = _mongo()
    await _seed_suggestion(mongo, "alice", "s1", "RELIANCE")
    agent = _RecordingAgent()

    await attach_theses(mongo, "alice", [{"id": "s1", "symbol": "RELIANCE"}], agent=agent)

    assert agent.seen_models == [None]


class _SentimentReport:
    def __init__(self, sentiment_score, thesis="Margins recovering."):
        self.thesis = thesis
        self.analyst_summary = ""
        self.sentiment_score = sentiment_score


class _SentimentAgent:
    def __init__(self, sentiment_score):
        self.sentiment_score = sentiment_score

    async def run(self, symbol):
        return _SentimentReport(self.sentiment_score)


async def _seed_scored(mongo, rule=0.8):
    await mongo["suggestions"].insert_one({
        "id": "s1", "user_id": "alice", "symbol": "RELIANCE", "mode": "LONGTERM", "status": "PENDING",
        "ai_thesis": None, "score": {"rule": rule, "ai": 0.0, "final": 0.71},
    })
    return {"id": "s1", "symbol": "RELIANCE", "score": {"rule": rule, "ai": 0.0, "final": 0.71}}


async def test_research_sentiment_replaces_the_neutral_ai_half_of_the_score():
    """At scan time the sentiment cache is empty, so every suggestion was
    scored with AI = 0. The research run's real reading must replace it,
    through the same capped formula."""
    mongo = _mongo()
    suggestion = await _seed_scored(mongo)

    await attach_theses(mongo, "alice", [suggestion], agent=_SentimentAgent(0.6))

    score = (await SuggestionStore(mongo).get("alice", "s1"))["score"]
    assert score["rule"] == 0.8
    assert score["ai"] == 0.6
    assert score["final"] == pytest.approx(0.7 * 0.8 + 0.3 * 0.8)  # (0.6 + 1) / 2 = 0.8


async def test_negative_sentiment_lowers_conviction_and_out_of_range_is_clamped():
    mongo = _mongo()
    suggestion = await _seed_scored(mongo)

    await attach_theses(mongo, "alice", [suggestion], agent=_SentimentAgent(-3.0))

    score = (await SuggestionStore(mongo).get("alice", "s1"))["score"]
    assert score["ai"] == -1.0
    assert score["final"] == pytest.approx(0.7 * 0.8)


async def test_no_sentiment_reading_leaves_the_score_alone():
    mongo = _mongo()
    suggestion = await _seed_scored(mongo)

    await attach_theses(mongo, "alice", [suggestion], agent=_RecordingAgent())

    assert (await SuggestionStore(mongo).get("alice", "s1"))["score"]["final"] == 0.71
