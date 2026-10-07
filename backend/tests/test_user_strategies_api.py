"""Compose, test, retire and re-test your own strategies over the API."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.builder import draft
from backend.database import db as database
from backend.routers import settings as settings_router
from backend.strategies.blocks.vocab import EXITS, FILTERS, SETUPS
from backend.tests.test_datalayer_news import FakeRedis
from backend.tests.test_settings_router import _user

SPEC = {"setup": {"gap": {"direction": "down", "min_pct": 1.0}}, "filters": {}, "side": "long",
        "stop": {"atr_multiple": 1.0}, "target": {"r_multiple": 2.0}}
URL = "/api/v1/strategies/built"


class CountingRedis(FakeRedis):
    async def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    async def expire(self, key, seconds):
        return True


@pytest.fixture
def env(monkeypatch):
    mongo, redis = AsyncMongoMockClient()["test_db"], CountingRedis()
    monkeypatch.setattr(database, "db", mongo)
    monkeypatch.setattr(database, "redis", redis)
    spawn = AsyncMock()
    monkeypatch.setattr(draft, "spawn_test", spawn)
    return mongo, redis, spawn


def _client(uid="alice"):
    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _user(uid)
    return TestClient(app)


def _body(name="My Gap", spec=SPEC):
    return {"name": name, "thesis": "gaps fill", "spec": spec}


def _spec(pct):
    return {**SPEC, "setup": {"gap": {"direction": "down", "min_pct": pct}}}


async def _put(mongo, slug, status, owner="alice", spec=SPEC):
    await mongo["built_strategies"].insert_one(
        {"slug": slug, "owner_id": owner, "status": status, "spec": spec, "thesis": "", "description": "",
         "verdict": "", "drafted_at": datetime(2026, 10, 2, tzinfo=timezone.utc)})


async def test_submit_stores_testing_doc_and_spawns(env):
    mongo, _, spawn = env
    r = _client().post(URL, json=_body())
    assert r.status_code == 201
    body = r.json()
    assert (body["slug"], body["status"], body["owner_id"]) == ("my-gap", "testing", "alice")
    assert body["description"].startswith("Long when") and body["thesis"] == "gaps fill"
    assert await mongo["built_strategies"].find_one({"slug": "my-gap", "owner_id": "alice"})
    spawn.assert_awaited_once_with("my-gap")


async def test_invalid_spec_is_422(env):
    r = _client().post(URL, json=_body(spec={"setup": {}}))
    assert r.status_code == 422 and r.json()["detail"] == "exactly one setup"


async def test_slug_gets_a_suffix_when_taken(env):
    mongo, _, _ = env
    await _put(mongo, "my-gap", "retired", owner="bob", spec=_spec(3.0))
    assert _client().post(URL, json=_body()).json()["slug"] == "my-gap-2"


async def test_empty_name_falls_back_to_the_spec_slug(env):
    assert _client().post(URL, json=_body(name="!!!")).json()["slug"] == "gap-down-long"


async def test_duplicate_of_own_refused_of_others_allowed(env):
    mongo, _, _ = env
    await _put(mongo, "theirs", "active", owner="bob")
    assert _client().post(URL, json=_body()).status_code == 201
    await mongo["built_strategies"].update_many({"owner_id": "alice"}, {"$set": {"status": "rejected"}})
    r = _client().post(URL, json=_body(name="again"))
    assert r.status_code == 422 and r.json()["detail"].startswith("duplicate of")


async def test_active_cap_409(env):
    mongo, redis, spawn = env
    for i in range(5):
        await _put(mongo, f"a{i}", "active", spec=_spec(1.0 + i))
    r = _client().post(URL, json=_body(spec=_spec(0.5)))
    assert r.status_code == 409 and r.json()["detail"] == "Retire one first."
    assert not redis.data  # a refusal does not burn a daily slot
    spawn.assert_not_awaited()


async def test_one_testing_at_a_time_409(env):
    mongo, _, _ = env
    await _put(mongo, "t", "testing", spec=_spec(3.0))
    r = _client().post(URL, json=_body())
    assert r.status_code == 409 and r.json()["detail"] == "A strategy of yours is still being tested."


async def test_daily_limit_429(env):
    mongo, _, _ = env
    for i in range(3):
        r = _client().post(URL, json=_body(name=f"n{i}", spec=_spec(1.0 + i)))
        assert r.status_code == 201
        await mongo["built_strategies"].update_many({}, {"$set": {"status": "rejected"}})
    r = _client().post(URL, json=_body(name="n4", spec=_spec(3.5)))
    assert r.status_code == 429
    assert _client("bob").post(URL, json=_body()).status_code == 201  # per user


async def test_retire_active_only_and_owner_only(env):
    mongo, _, _ = env
    await _put(mongo, "a", "active")
    await _put(mongo, "r", "rejected")
    assert _client("bob").post(f"{URL}/a/retire").status_code == 404
    assert _client().post(f"{URL}/r/retire").status_code == 409
    assert _client().post(f"{URL}/a/retire").status_code == 200
    assert (await mongo["built_strategies"].find_one({"slug": "a"}))["status"] == "retired"


async def test_retest_rejected_counts_toward_limits_and_spawns(env):
    mongo, redis, spawn = env
    await _put(mongo, "r", "rejected")
    await _put(mongo, "a", "active", spec=_spec(3.0))
    assert _client().post(f"{URL}/a/retest").status_code == 409
    assert _client("bob").post(f"{URL}/r/retest").status_code == 404
    assert _client().post(f"{URL}/r/retest").status_code == 200
    assert (await mongo["built_strategies"].find_one({"slug": "r"}))["status"] == "testing"
    spawn.assert_awaited_once_with("r")
    assert any(k.startswith("rate:strategies:submit:alice:") for k in redis.data)
    await _put(mongo, "r2", "rejected", spec=_spec(2.0))
    assert _client().post(f"{URL}/r2/retest").status_code == 409  # r is still testing


async def test_other_users_strategy_is_invisible_and_untouchable(env):
    mongo, _, _ = env
    await _put(mongo, "secret", "active", owner="bob")
    await _put(mongo, "global", "active", owner=None, spec=_spec(3.0))
    body = _client().get(URL).json()
    assert [r["slug"] for r in body["active"]] == ["global"] and body["active"][0]["mine"] is False
    assert _client("bob").get(URL).json()["active"][0]["mine"] in (True, False)
    for verb in ("retire", "retest"):
        assert _client().post(f"{URL}/secret/{verb}").status_code == 404
        assert _client().post(f"{URL}/global/{verb}").status_code == 404  # the AI's are not the user's to touch
    assert _client().post(f"{URL}/nope/retire").json()["detail"] == "No such strategy"


async def test_list_marks_mine(env):
    mongo, _, _ = env
    await _put(mongo, "m", "active")
    assert _client().get(URL).json()["active"][0]["mine"] is True


async def test_spawn_failure_leaves_draft_testing(env):
    mongo, _, spawn = env
    spawn.side_effect = OSError("no fork")
    r = _client().post(URL, json=_body())
    assert r.status_code == 201 and r.json()["status"] == "testing"
    assert (await mongo["built_strategies"].find_one({"slug": "my-gap"}))["status"] == "testing"


def test_vocabulary_matches_vocab_module(env):
    body = _client().get("/api/v1/strategies/vocabulary").json()
    assert set(body) == {"setups", "filters", "exits"}
    assert body["setups"]["gap"] == {"direction": {"choices": ["up", "down"]}, "min_pct": {"min": 0.5, "max": 4.0, "step": 0.25}}
    assert body["filters"]["time_window"]["start"] == {"time": ["09:20", "14:45"]}
    assert body["exits"]["stop"]["setup_bar"] == {"flag": True}
    assert set(body["setups"]) == set(SETUPS) and set(body["filters"]) == set(FILTERS) and set(body["exits"]) == set(EXITS)


def test_describe_endpoint(env):
    r = _client().post("/api/v1/strategies/describe", json={"spec": SPEC})
    assert r.status_code == 200 and r.json()["spec"] == SPEC and r.json()["description"].startswith("Long when")
    r = _client().post("/api/v1/strategies/describe", json={"spec": {"setup": {}}})
    assert r.status_code == 422 and r.json()["detail"] == "exactly one setup"
