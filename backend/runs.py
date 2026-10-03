"""Durable record of paper-trading runs (collection `trading_runs`).

backend/routers/trading.py tracks live runs in a process-global dict of
asyncio.Tasks, which cannot answer "what is running for this user?" after a
restart and is invisible to any other process. This store is the durable
half: the task dict stays the thing that can be cancelled, while these rows
are what the API and the UI read.
"""

from datetime import datetime, timezone
from typing import Optional

ACTIVE = "RUNNING"


class RunStore:
    def __init__(self, db) -> None:
        self.collection = db["trading_runs"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("run_id", unique=True)
        await self.collection.create_index([("user_id", 1), ("status", 1)])

    async def create(
        self, run_id: str, user_id: str, mode: str, universe: list[str], params: dict
    ) -> None:
        await self.collection.insert_one({
            "run_id": run_id,
            "user_id": user_id,
            "mode": mode,
            "universe": universe,
            "params": params,
            "status": ACTIVE,
            "started_at": datetime.now(timezone.utc),
            "stopped_at": None,
            "error": None,
        })

    async def set_progress(self, run_id: str, progress: dict) -> None:
        await self.collection.update_one({"run_id": run_id}, {"$set": {"progress": progress}})

    async def mark_stopped(self, run_id: str) -> None:
        await self._close(run_id, status="STOPPED", error=None)

    async def mark_error(self, run_id: str, error: str) -> None:
        await self._close(run_id, status="ERROR", error=error)

    async def _close(self, run_id: str, status: str, error: Optional[str]) -> None:
        await self.collection.update_one(
            {"run_id": run_id},
            {"$set": {"status": status, "error": error, "stopped_at": datetime.now(timezone.utc)}},
        )

    async def get(self, run_id: str) -> Optional[dict]:
        doc = await self.collection.find_one({"run_id": run_id})
        return _clean(doc) if doc else None

    async def list_active(self, user_id: str) -> list[dict]:
        cursor = self.collection.find({"user_id": user_id, "status": ACTIVE})
        return [_clean(doc) for doc in await cursor.to_list(length=None)]

    async def list_for_user(self, user_id: str, limit: int = 20) -> list[dict]:
        cursor = self.collection.find({"user_id": user_id}).sort("started_at", -1).limit(limit)
        return [_clean(doc) for doc in await cursor.to_list(length=None)]

    async def close_orphaned(self) -> int:
        """Called at startup: any row still RUNNING belongs to a process that
        no longer exists, since the asyncio.Task driving it died with it."""
        result = await self.collection.update_many(
            {"status": ACTIVE},
            {"$set": {
                "status": "STOPPED",
                "error": "orphaned by restart",
                "stopped_at": datetime.now(timezone.utc),
            }},
        )
        return result.modified_count


def run_summary(run: dict) -> dict:
    """What the chat assistant sees of a run: identity plus live progress
    (bars scanned, signals, orders, last bar), so it can say how the engine
    is doing rather than only that it is running."""
    started_at = run.get("started_at")
    return {
        "run_id": run["run_id"], "mode": run["mode"], "origin": run["params"].get("origin"),
        "started_at": started_at.isoformat() if started_at else None,
        "scrip": len(run.get("universe") or []),
        "progress": run.get("progress") or "no bar processed yet",
    }


def _clean(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc
