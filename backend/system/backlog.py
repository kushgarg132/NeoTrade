"""The admin's backlog of future enhancements: one app-wide collection (no
user_id -- it is the project's own list), edited from /system/future."""

from datetime import datetime, timezone
from typing import Literal, Optional

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, Field

COLLECTION = "backlog"
Area = Literal["System", "Data", "Trading", "AI", "News", "Journal", "UI", "Ops", "Product"]
Status = Literal["idea", "next", "doing", "done", "dropped"]
Effort = Optional[Literal["S", "M", "L"]]
STATUS_ORDER = ("doing", "next", "idea", "done", "dropped")


class ItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=140)
    area: Area
    status: Status = "idea"
    why: str = Field("", max_length=2000)
    notes: str = Field("", max_length=4000)
    effort: Effort = None
    source: str = Field("", max_length=140)


class ItemPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=140)
    area: Optional[Area] = None
    status: Optional[Status] = None
    why: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=4000)
    effort: Effort = None
    source: Optional[str] = Field(None, max_length=140)
    rank: Optional[float] = None


def _oid(item_id: str) -> Optional[ObjectId]:
    try:
        return ObjectId(item_id)
    except (InvalidId, TypeError):
        return None


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    doc.setdefault("done_at", None)
    return doc


async def list_items(db) -> list[dict]:
    docs = await db[COLLECTION].find().to_list(length=None)
    docs.sort(key=lambda d: (STATUS_ORDER.index(d["status"]), d.get("rank", 0)))
    return [_out(d) for d in docs]


async def create(db, item: ItemIn) -> dict:
    last = await db[COLLECTION].find_one({"status": item.status}, sort=[("rank", -1)])
    now = datetime.now(timezone.utc)
    doc = {**item.model_dump(), "rank": (last["rank"] + 1) if last else 0,
           "created_at": now, "updated_at": now, "done_at": now if item.status == "done" else None}
    result = await db[COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    return _out(doc)


async def update(db, item_id: str, patch: ItemPatch) -> Optional[dict]:
    oid = _oid(item_id)
    current = oid and await db[COLLECTION].find_one({"_id": oid})
    if not current:
        return None
    changes = patch.model_dump(exclude_unset=True)
    now = datetime.now(timezone.utc)
    if "status" in changes and changes["status"] != current["status"]:
        changes["done_at"] = now if changes["status"] == "done" else None
    changes["updated_at"] = now
    await db[COLLECTION].update_one({"_id": oid}, {"$set": changes})
    return _out({**current, **changes})


async def delete(db, item_id: str) -> bool:
    oid = _oid(item_id)
    return bool(oid) and (await db[COLLECTION].delete_one({"_id": oid})).deleted_count == 1
