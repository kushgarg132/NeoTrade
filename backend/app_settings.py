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
# Per-task tiers: each LLM call site asks for one. An unset tier falls back
# to the single model above, so nothing changes until an admin sets one.
TIERS = ("fast", "standard", "deep")
_cached_tiers: dict = {}
# LLM features an admin switched off (Phase 17.4.2); the names are the
# `feature=` every call site passes (backend/tests/test_llm_call_tiers.py).
FEATURES = ("news", "plan", "research", "chat", "portfolio", "learning")
_cached_off: set = set()
_cache_loaded_at: float = 0.0


async def _refresh(db=None) -> None:
    """Re-reads the settings at most once per _TTL_SECONDS per process."""
    global _cached_llm_model, _cached_tiers, _cached_off, _cache_loaded_at

    if time.monotonic() - _cache_loaded_at >= _TTL_SECONDS:
        if db is None:
            from backend.database import db as _db
            db = _db.db
        if db is None:
            return  # not connected (a script, a test): keep what is cached
        store = AppSettingsStore(db)
        _cached_llm_model = await store.get_llm_model()
        _cached_tiers = await store.get_llm_tiers()
        _cached_off = set(await store.get_features_off())
        _cache_loaded_at = time.monotonic()


async def feature_enabled(feature: Optional[str], db=None) -> bool:
    await _refresh(db)
    return feature not in _cached_off


async def current_llm_model(db=None, tier: Optional[str] = None) -> str:
    from backend.configs.settings import settings

    await _refresh(db)
    return (tier and _cached_tiers.get(tier)) or _cached_llm_model or settings.OMNIROUTE_MODEL


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

    async def get_llm_tiers(self) -> dict:
        doc = await self.collection.find_one({"_id": _DOC_ID})
        stored = (doc or {}).get("llm_tiers") or {}
        return {tier: stored.get(tier) for tier in TIERS}

    async def set_llm_tier(self, tier: str, model: Optional[str]) -> None:
        """None clears the tier, so it falls back to the single model."""
        global _cached_tiers, _cache_loaded_at
        if tier not in TIERS:
            raise ValueError(f"Unknown tier {tier!r}")
        update = {"$set": {f"llm_tiers.{tier}": model, "updated_at": datetime.now(timezone.utc)}}
        await self.collection.update_one({"_id": _DOC_ID}, update, upsert=True)
        _cached_tiers = await self.get_llm_tiers()
        _cache_loaded_at = time.monotonic()

    async def get_features_off(self) -> list[str]:
        doc = await self.collection.find_one({"_id": _DOC_ID})
        return sorted((doc or {}).get("llm_features_off") or [])

    async def set_feature(self, feature: str, enabled: bool) -> None:
        global _cached_off
        if feature not in FEATURES:
            raise ValueError(f"Unknown feature {feature!r}")
        op = "$pull" if enabled else "$addToSet"
        await self.collection.update_one(
            {"_id": _DOC_ID}, {op: {"llm_features_off": feature}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        _cached_off = set(await self.get_features_off())

    async def get_portfolio_verdicts(self) -> str:
        """Who sees SELL / HOLD / ADD on the Portfolio page: "admin" (the
        default) or "all". Verdicts for every user need SEBI Research Analyst
        registration first -- see PRODUCT.md."""
        doc = await self.collection.find_one({"_id": _DOC_ID})
        return (doc or {}).get("portfolio_verdicts") or "admin"

    async def set_portfolio_verdicts(self, audience: str) -> None:
        await self.collection.update_one(
            {"_id": _DOC_ID},
            {"$set": {"portfolio_verdicts": audience, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    async def load_into_cache(self) -> None:
        global _cached_llm_model, _cached_tiers, _cached_off, _cache_loaded_at
        _cached_llm_model = await self.get_llm_model()
        _cached_tiers = await self.get_llm_tiers()
        _cached_off = set(await self.get_features_off())
        _cache_loaded_at = time.monotonic()
