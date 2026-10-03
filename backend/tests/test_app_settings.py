"""Deployment-wide settings in Mongo, replacing the .env rewriting.

current_llm_model() is called from LLMService.get_llm() on (effectively)
every LLM request, so it can't read Mongo every time -- but with more than
one worker, a process-local cache that only refreshes when THIS process
calls set_llm_model means a second worker never sees an admin's change. The
fix is a short TTL: re-read Mongo at most once every 30 seconds.
"""

from mongomock_motor import AsyncMongoMockClient

from backend import app_settings as app_settings_module
from backend.app_settings import AppSettingsStore, current_llm_model


def _store():
    return AppSettingsStore(AsyncMongoMockClient()["test_db"])


async def test_model_starts_unset():
    assert await _store().get_llm_model() is None


async def test_setting_the_model_persists_it():
    store = _store()
    await store.set_llm_model("aug/sonnet5-high")
    assert await store.get_llm_model() == "aug/sonnet5-high"


async def test_setting_the_model_replaces_rather_than_accumulates():
    store = _store()
    await store.set_llm_model("first")
    await store.set_llm_model("second")

    assert await store.get_llm_model() == "second"
    assert await store.collection.count_documents({}) == 1


async def test_current_model_falls_back_to_the_configured_default(monkeypatch):
    from backend.configs import settings as settings_module

    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    monkeypatch.setattr(settings_module.settings, "OMNIROUTE_MODEL", "env/default-model")

    mongo = AsyncMongoMockClient()["test_db"]
    assert await current_llm_model(db=mongo) == "env/default-model"


async def test_saving_a_model_takes_effect_immediately_in_this_process(monkeypatch):
    """get_llm() is called per request and awaits current_llm_model(), which
    caches for 30s -- but set_llm_model resets that clock in THIS process, so
    the admin who just changed it sees the new value on their very next
    call, no restart or TTL wait needed."""
    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    store = _store()

    await store.set_llm_model("aug/sonnet5-high")

    assert await current_llm_model(db=store._db) == "aug/sonnet5-high"


async def test_the_stored_model_is_loaded_at_startup(monkeypatch):
    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    store = _store()
    await store.collection.update_one(
        {"_id": "singleton"}, {"$set": {"llm_model": "persisted/model"}}, upsert=True
    )

    await store.load_into_cache()

    assert await current_llm_model(db=store._db) == "persisted/model"


async def test_a_read_within_the_ttl_window_does_not_touch_mongo_again(monkeypatch):
    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    store = _store()
    await store.set_llm_model("aug/sonnet5-high")

    fake_time = [1_000.0]
    monkeypatch.setattr(app_settings_module.time, "monotonic", lambda: fake_time[0])
    # Force the cache to look stale once, then observe it does NOT refetch
    # again for a second read 5s later (well inside the 30s TTL).
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", fake_time[0])

    calls = []
    real_get = AppSettingsStore.get_llm_model

    async def counting_get(self):
        calls.append(1)
        return await real_get(self)

    monkeypatch.setattr(AppSettingsStore, "get_llm_model", counting_get)

    fake_time[0] += 5
    first = await current_llm_model(db=store._db)
    fake_time[0] += 5
    second = await current_llm_model(db=store._db)

    assert first == second == "aug/sonnet5-high"
    assert calls == []  # still within the TTL window from the fixture's own set_llm_model reset


async def test_a_read_past_the_ttl_window_refetches_from_mongo(monkeypatch):
    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    store = _store()
    await store.set_llm_model("first")

    fake_time = [1_000.0]
    monkeypatch.setattr(app_settings_module.time, "monotonic", lambda: fake_time[0])
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", fake_time[0])

    first = await current_llm_model(db=store._db)
    await store.collection.update_one({"_id": "singleton"}, {"$set": {"llm_model": "second"}})
    fake_time[0] += 31  # past the 30s TTL window

    second = await current_llm_model(db=store._db)

    assert first == "first"
    assert second == "second"


async def test_a_tier_model_wins_over_the_single_model_and_falls_back_to_it(monkeypatch):
    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cached_tiers", {})
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    store = _store()
    await store.set_llm_model("auto/claude-opus")
    await store.set_llm_tier("fast", "agy/gemini-3-flash")

    assert await current_llm_model(db=store._db, tier="fast") == "agy/gemini-3-flash"
    assert await current_llm_model(db=store._db, tier="standard") == "auto/claude-opus"
    assert await current_llm_model(db=store._db) == "auto/claude-opus"
    assert await store.get_llm_tiers() == {"fast": "agy/gemini-3-flash", "standard": None, "deep": None}

    await store.set_llm_tier("fast", None)  # cleared: back to the single model
    assert await current_llm_model(db=store._db, tier="fast") == "auto/claude-opus"


async def test_tiers_survive_the_ttl_refresh(monkeypatch):
    monkeypatch.setattr(app_settings_module, "_cached_tiers", {})
    store = _store()
    await store.collection.update_one(
        {"_id": "singleton"}, {"$set": {"llm_model": "m", "llm_tiers": {"deep": "auto/claude-opus"}}}, upsert=True
    )
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    assert await current_llm_model(db=store._db, tier="deep") == "auto/claude-opus"
