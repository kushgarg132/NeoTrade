"""Why the user holds a stock: their own note, target, stop and review date.
One doc per (user, symbol) in `holding_theses`."""

from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, model_validator

SYMBOL = r"^[A-Z0-9&\-]{1,20}$"


class ThesisIn(BaseModel):
    why: str = Field("", max_length=2000)
    target: Optional[float] = Field(None, gt=0)
    stop: Optional[float] = Field(None, gt=0)
    review_by: Optional[date] = None

    @model_validator(mode="after")
    def _stop_below_target(self):
        if self.target is not None and self.stop is not None and self.stop >= self.target:
            raise ValueError("stop must be below target")
        return self


class ThesisStore:
    def __init__(self, db):
        self.col = db["holding_theses"]

    async def ensure_indexes(self):
        await self.col.create_index([("user_id", 1), ("symbol", 1)], unique=True)

    async def get(self, user_id: str, symbol: str) -> Optional[dict]:
        return await self.col.find_one({"user_id": user_id, "symbol": symbol}, {"_id": 0})

    async def all(self, user_id: str) -> dict[str, dict]:
        return {d["symbol"]: d async for d in self.col.find({"user_id": user_id}, {"_id": 0})}

    async def put(self, user_id: str, symbol: str, body: ThesisIn) -> dict:
        doc = body.model_dump(mode="json")  # review_by -> ISO string, which BSON can store
        doc["updated_at"] = datetime.now(timezone.utc)
        await self.col.update_one({"user_id": user_id, "symbol": symbol},
                                  {"$set": doc}, upsert=True)
        return await self.get(user_id, symbol)
