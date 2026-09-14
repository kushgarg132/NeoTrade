"""backend/suggestions/thesis.py: attaching an LLM-derived rationale to
fresh suggestions using the user's own saved model preference, if any.
"""

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
