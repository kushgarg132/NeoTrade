"""Shared plumbing: at most one model call per user, kind and period (Redis
NX claim), figures grounded in the facts given, a failure keeps the last stored
text and backs off. Prompts live in backend/prompts/*.md."""

import json
import logging
import re
from datetime import datetime, timezone
from html import unescape
from typing import Awaitable, Callable, Optional

from backend.ai.grounding import grounded
from backend.llm import DailyLimitReached, llm_service

logger = logging.getLogger(__name__)

COLLECTION = "ai_summaries"
FAIL_BACKOFF = 6 * 3600  # a failed attempt is not retried for 6 hours (4 tries a day at most)
_TAGS = re.compile(r"<[^>]*>")
Build = Callable[[], Awaitable[Optional[tuple[str, str, object]]]]


def plain(html: str) -> str:
    """Telegram HTML as plain text lines."""
    return unescape(_TAGS.sub("", html or "")).strip()


def _rounded(node):
    """Floats to 2 dp, so a model never echoes 2.0491571895134424% back (grounding allows the rounding)."""
    if isinstance(node, float):
        return round(node, 2)
    if isinstance(node, dict):
        return {k: _rounded(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_rounded(v) for v in node]
    return node


def as_facts(data) -> str:
    return json.dumps(_rounded(data), default=str, ensure_ascii=False, indent=1)


def pct(x: Optional[float]) -> Optional[float]:
    """A fraction as a percentage, the unit summaries state returns in."""
    return None if x is None else round(x * 100, 2)


def failed(text: Optional[str]) -> bool:
    return not text or text == "LLM_DISABLED" or text.startswith("Error generating response")


def claim_key(user_id: str, kind: str, key: str) -> str:
    return f"summary:{kind}:{user_id}:{key}"


async def get(db, user_id: str, kind: str, key: str) -> Optional[dict]:
    return await db[COLLECTION].find_one({"user_id": user_id, "kind": kind, "key": key}, {"_id": 0, "user_id": 0})


async def latest(db, user_id: str, kind: str) -> Optional[dict]:
    return await db[COLLECTION].find_one({"user_id": user_id, "kind": kind}, {"_id": 0, "user_id": 0},
                                         sort=[("at", -1)])


def shown(doc: Optional[dict]) -> Optional[dict]:
    """What the API sends: the text, its period key and when it was written (tz-aware)."""
    if not doc:
        return None
    at = doc["at"] if doc["at"].tzinfo else doc["at"].replace(tzinfo=timezone.utc)
    return {"text": doc["text"], "key": doc["key"], "at": at}


async def produce(db, redis, user_id: str, kind: str, key: str, build: Build, *, tier: str, feature: str,
                  ttl: int, max_lines: Optional[int] = None) -> Optional[dict]:
    """The stored summary just written, or None (already done this period, nothing to say, model
    unavailable or over budget: the last stored text stays). `build` runs only after the claim and
    returns (system prompt, user prompt, facts the figures must come from) or None."""
    if redis is None:
        return None
    claim = claim_key(user_id, kind, key)
    if not await redis.set(claim, "1", nx=True, ex=ttl):
        return None
    if await get(db, user_id, kind, key):  # Redis lost the claim, Mongo did not
        return None
    try:
        built = await build()
        if built is None:
            await redis.delete(claim)  # no data yet: the next pass may try
            return None
        system, prompt, facts = built
        text = ((await llm_service.get_completion(prompt, system_prompt=system, tier=tier, feature=feature)) or "").strip()
    except DailyLimitReached:
        text = ""
    except Exception as exc:
        logger.warning("summary %s for %s failed: %s", kind, user_id, exc)
        text = ""
    if not failed(text):
        text, _ = await grounded(text, facts, None)  # a sentence with an unsupported figure is dropped
        lines = [ln.strip(" -•*\t") for ln in text.splitlines() if ln.strip(" -•*\t")]
        text = "\n".join(lines[:max_lines] if max_lines else lines)
    if failed(text):
        await redis.set(claim, "1", ex=FAIL_BACKOFF)
        return None
    doc = {"user_id": user_id, "kind": kind, "key": key, "text": text, "at": datetime.now(timezone.utc)}
    await db[COLLECTION].update_one({"user_id": user_id, "kind": kind, "key": key}, {"$set": doc}, upsert=True)
    return doc
