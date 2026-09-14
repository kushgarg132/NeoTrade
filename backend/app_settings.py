"""Deployment-wide settings that used to be rewritten into .env at runtime
(collection `app_settings`, one document).

Writing .env from a request mutated shared process state, did not survive
more than one worker, and was reachable by anyone signed in. These settings
are genuinely deployment-wide rather than per-user, so they stay shared --
but they live in the database and only an admin may change them.

current_llm_model() is called from LLMService.get_llm() on effectively every
LLM request. With one worker, caching it in-process and refreshing only on
a local set_llm_model call was enough. With more than one, a second worker
would keep serving the stale value until it restarted -- so the cache now
has a short TTL (re-read Mongo at most once every 30s) instead of relying
purely on a local write to invalidate it.
"""

import time
from datetime import datetime, timezone
from typing import Optional

_DOC_ID = "singleton"
_TTL_SECONDS = 30

_cached_llm_model: Optional[str] = None
_cache_loaded_at: float = 0.0


async def current_llm_model(db=None) -> str:
    from backend.configs.settings import settings

    global _cached_llm_model, _cache_loaded_at

    if time.monotonic() - _cache_loaded_at >= _TTL_SECONDS:
        if db is None:
            from backend.database import db as _db
            db = _db.db
        _cached_llm_model = await AppSettingsStore(db).get_llm_model()
        _cache_loaded_at = time.monotonic()

    return _cached_llm_model or settings.OMNIROUTE_MODEL


class AppSettingsStore:
    def __init__(self, db) -> None:
        self._db = db

    @property
    def collection(self):
        return self._db["app_settings"]

    async def get_llm_model(self) -> Optional[str]:
        doc = await self.collection.find_one({"_id": _DOC_ID})
        return (doc or {}).get("llm_model")

    async def set_llm_model(self, model: str) -> None:
        global _cached_llm_model, _cache_loaded_at
        await self.collection.update_one(
            {"_id": _DOC_ID},
            {"$set": {"llm_model": model, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        _cached_llm_model = model
        _cache_loaded_at = time.monotonic()

    async def load_into_cache(self) -> None:
        global _cached_llm_model, _cache_loaded_at
        _cached_llm_model = await self.get_llm_model()
        _cache_loaded_at = time.monotonic()
