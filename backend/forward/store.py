"""The forward record: every decision the system makes, written once at decision
time and scored later against what happened. Never gates money; writers and
readers never raise into callers."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from backend.core.market_calendar import add_trading_days
from backend.datalayer import bars

logger = logging.getLogger(__name__)
COLLECTION = "forward_records"


def record_id(source: str, name: str, symbol: str, day: date, side: str) -> str:
    return f"{source}:{name}:{symbol}:{day.isoformat()}:{side}"


class ForwardStore:
    def __init__(self, db):
        self.col = db[COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.col.create_index([("outcome", 1), ("due_date", 1)])
        await self.col.create_index([("source", 1), ("name", 1), ("decided_at", -1)])

    async def record(self, *, source: str, name: Optional[str], user_id: str, symbol: str, side: str,
                     decided_at: datetime, intraday: bool, ref_price: Optional[float], horizon_days: int,
                     predicted: Optional[dict] = None) -> bool:
        """True when a new record was written; False on a duplicate or any error."""
        try:
            name = name or "unknown"
            day = bars.today_ist(decided_at)
            due = day if intraday else add_trading_days(day, horizon_days + 1)
            res = await self.col.update_one(
                {"_id": record_id(source, name, symbol, day, side)},
                {"$setOnInsert": {
                    "source": source, "name": name, "user_id": user_id, "symbol": symbol, "side": side,
                    "decided_at": decided_at, "intraday": intraday, "ref_price": ref_price,
                    "horizon_days": horizon_days, "due_date": due.isoformat(), "predicted": predicted,
                    "outcome": None, "scored_at": None,
                }},
                upsert=True,
            )
            return res.upserted_id is not None
        except Exception as exc:
            logger.warning("forward record not written: %s", exc)
            return False

    async def due(self, now: datetime) -> list[dict]:
        return await self.col.find(
            {"outcome": None, "due_date": {"$lte": bars.today_ist(now).isoformat()}}
        ).to_list(length=None)

    async def set_outcome(self, record_id: str, outcome: dict, now: datetime) -> None:
        await self.col.update_one({"_id": record_id}, {"$set": {"outcome": outcome, "scored_at": now}})

    async def list(self, source: Optional[str] = None, name: Optional[str] = None, limit: int = 200) -> list[dict]:
        q = {k: v for k, v in (("source", source), ("name", name)) if v}
        return await self.col.find(q).sort("decided_at", -1).to_list(length=limit)

    async def scored(self, source: Optional[str] = None) -> list[dict]:
        q = {"outcome": {"$ne": None}, "outcome.void": {"$ne": True}}
        if source:
            q["source"] = source
        return await self.col.find(q).to_list(length=None)
