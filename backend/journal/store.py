"""The trade journal's persistence. Collection `journal_trades`: one document
per broker execution, `_id` = user:broker:trade_id, so re-syncing the same
day or re-importing the same CSV never duplicates a fill. Collection
`journal_notes`: the user's own note and tags per round trip.
"""

from datetime import datetime, timezone

from pymongo.errors import BulkWriteError

from backend.core.models import BrokerTrade


class JournalStore:
    def __init__(self, db) -> None:
        self.trades = db["journal_trades"]
        self.notes = db["journal_notes"]

    async def ensure_indexes(self) -> None:
        await self.trades.create_index([("user_id", 1), ("traded_at", 1)])
        await self.notes.create_index("user_id")

    async def add_trades(self, user_id: str, broker: str, trades: list[BrokerTrade], source: str) -> int:
        """Returns how many were new. Existing fills are left untouched."""
        if not trades:
            return 0
        now = datetime.now(timezone.utc)
        docs = {
            f"{user_id}:{broker}:{t.trade_id}": {
                **t.model_dump(mode="python"), "side": t.side.value,
                "user_id": user_id, "broker": broker, "source": source, "imported_at": now,
            }
            for t in trades
        }
        existing = await self.trades.find({"_id": {"$in": list(docs)}}, {"_id": 1}).to_list(length=None)
        for doc in existing:
            docs.pop(doc["_id"])
        if not docs:
            return 0
        try:
            await self.trades.insert_many([{"_id": k, **v} for k, v in docs.items()], ordered=False)
        except BulkWriteError as exc:
            # A concurrent sync inserted some of the same fills first.
            return exc.details["nInserted"]
        return len(docs)

    async def list_trades(self, user_id: str, since: datetime | None = None) -> list[dict]:
        # ponytail: loads a user's whole history; page by date once someone has 50k+ fills
        query = {"user_id": user_id}
        if since is not None:
            query["traded_at"] = {"$gte": since}
        docs = await self.trades.find(query).to_list(length=None)
        for d in docs:
            if d["traded_at"].tzinfo is None:  # Mongo hands back naive UTC
                d["traded_at"] = d["traded_at"].replace(tzinfo=timezone.utc)
        return docs

    async def notes_for(self, user_id: str) -> dict[str, dict]:
        docs = await self.notes.find({"user_id": user_id}).to_list(length=None)
        return {d["round_trip_id"]: {"note": d.get("note", ""), "tags": d.get("tags", [])} for d in docs}

    async def set_note(self, user_id: str, round_trip_id: str, note: str, tags: list[str]) -> None:
        await self.notes.update_one(
            {"_id": f"{user_id}:{round_trip_id}"},
            {"$set": {
                "user_id": user_id, "round_trip_id": round_trip_id, "note": note,
                "tags": tags, "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
