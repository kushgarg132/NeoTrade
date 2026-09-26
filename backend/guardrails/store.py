"""Guardrail breaches already alerted (collection `guardrail_events`, one per
user + IST day + breach key -- the dedupe that makes a 60-second poll send
one alert, not hundreds) and where to send alerts (collection
`alert_channels`, one per user; not part of prefs, since a user must not be
able to point alerts at a chat they did not link themselves)."""

from datetime import date, datetime, timezone
from typing import Optional


class GuardrailStore:
    def __init__(self, db) -> None:
        self.events = db["guardrail_events"]
        self.channels = db["alert_channels"]

    async def ensure_indexes(self) -> None:
        await self.events.create_index([("user_id", 1), ("day", 1)])

    async def record(self, user_id: str, day: date, breach: dict) -> bool:
        """True only the first time this breach is seen that day."""
        result = await self.events.update_one(
            {"_id": f"{user_id}:{day.isoformat()}:{breach['key']}"},
            {"$setOnInsert": {**breach, "user_id": user_id, "day": day.isoformat(),
                              "at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return result.upserted_id is not None

    async def events_for(self, user_id: str, day: date) -> list[dict]:
        docs = await self.events.find({"user_id": user_id, "day": day.isoformat()}).to_list(length=None)
        docs.sort(key=lambda d: d["at"])
        return [{k: v for k, v in d.items() if k not in ("_id", "user_id")} for d in docs]

    async def telegram_chat(self, user_id: str) -> Optional[int]:
        doc = await self.channels.find_one({"_id": user_id})
        return doc.get("telegram_chat_id") if doc else None

    async def set_telegram_chat(self, user_id: str, chat_id: Optional[int]) -> None:
        await self.channels.update_one(
            {"_id": user_id}, {"$set": {"telegram_chat_id": chat_id}}, upsert=True,
        )
