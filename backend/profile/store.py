"""user_profiles: one document per user (_id = user_id = the user id).
Every method is keyed by the caller's user id; nothing lists profiles."""

import re
import uuid
from datetime import datetime, timezone

from backend.profile.models import MAX_MEMORIES, MAX_MEMORY_CHARS, MemoryRefused


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


class ProfileStore:
    def __init__(self, db):
        self.collection = db["user_profiles"]

    async def get(self, user_id: str) -> dict:
        doc = await self.collection.find_one({"_id": user_id}) or {}
        profile = {k: v for k, v in doc.items() if k not in ("_id", "user_id")}
        profile.setdefault("memories", [])
        return profile

    async def update(self, user_id: str, fields: dict) -> dict:
        set_ = {k: v for k, v in fields.items() if v not in ("", [], None)}
        unset = {k: "" for k, v in fields.items() if v in ("", [], None)}
        ops = {"$set": {**set_, "user_id": user_id, "updated_at": datetime.now(timezone.utc)}}
        if unset:
            ops["$unset"] = unset
        await self.collection.update_one({"_id": user_id}, ops, upsert=True)
        return await self.get(user_id)

    async def add_memory(self, user_id: str, text: str, source: str) -> dict:
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text:
            raise MemoryRefused("There is nothing to remember.")
        if len(text) > MAX_MEMORY_CHARS:
            raise MemoryRefused(f"A memory can be at most {MAX_MEMORY_CHARS} characters.")
        memories = (await self.get(user_id))["memories"]
        if any(_norm(m["text"]) == _norm(text) for m in memories):
            raise MemoryRefused("That is already in your profile memory.")
        if len(memories) >= MAX_MEMORIES:
            raise MemoryRefused(f"Your profile memory is full ({MAX_MEMORIES}). Delete one on the Profile page first.")
        memory = {"id": uuid.uuid4().hex, "text": text, "source": source, "created_at": datetime.now(timezone.utc)}
        await self.collection.update_one(
            {"_id": user_id},
            {"$push": {"memories": memory}, "$set": {"user_id": user_id, "updated_at": memory["created_at"]}},
            upsert=True,
        )
        return memory

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        result = await self.collection.update_one({"_id": user_id}, {"$pull": {"memories": {"id": memory_id}}})
        return result.modified_count == 1
