"""Mongo-backed store for AI trade suggestions (collection `suggestions`).

A suggestion is a sized, scored, stop-and-target-bearing order the engine
would have placed on its own, held back for a human decision. It keeps the
engine's own numbers rather than a fresh opinion, so approving one places
exactly the trade the strategy asked for.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.ws.hub import hub

PENDING = "PENDING"
DECIDED_STATUSES = ("APPROVED", "REJECTED", "EXPIRED", "EXECUTED")

# Long-term signals are computed off daily bars, so one left undecided for a
# week is stale advice, not a standing order.
DEFAULT_TTL = timedelta(days=3)


class SuggestionStore:
    def __init__(self, db) -> None:
        self.collection = db["suggestions"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("id", unique=True)
        await self.collection.create_index([("user_id", 1), ("status", 1), ("mode", 1)])

    async def create(
        self,
        user_id: str,
        proposal,
        source: str,
        run_id: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        now: Optional[datetime] = None,
    ) -> dict:
        now = now or datetime.now(timezone.utc)
        order, intent, score = proposal.order, proposal.intent, proposal.score

        doc = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "run_id": run_id,
            "symbol": order.symbol,
            "mode": proposal.mode,
            "side": order.side.value if hasattr(order.side, "value") else order.side,
            "quantity": order.quantity,
            "entry_ref": proposal.entry,
            "stop": intent.stop_hint,
            "target": intent.target_hint,
            "notional": order.quantity * proposal.entry,
            "option_contract": getattr(proposal, "option_contract", None),
            "strength": intent.strength,
            "reason_codes": list(intent.reason_codes),
            "score": {"rule": score.rule_score, "ai": score.ai_score, "final": score.final},
            "ai_thesis": None,
            "source": source,
            "status": PENDING,
            "created_at": now,
            "expires_at": expires_at or (now + DEFAULT_TTL),
            "decided_at": None,
            "reason": None,
            "order_id": None,
        }
        await self.collection.insert_one(dict(doc))
        clean = _clean(doc)
        await hub.publish(user_id, "suggestions", "created", clean)
        return clean

    async def get(self, user_id: str, suggestion_id: str) -> Optional[dict]:
        doc = await self.collection.find_one({"user_id": user_id, "id": suggestion_id})
        return _clean(doc) if doc else None

    async def has_pending(self, user_id: str, symbol: str, mode: str) -> bool:
        return await self.collection.find_one(
            {"user_id": user_id, "symbol": symbol, "mode": mode, "status": PENDING}
        ) is not None

    async def list(
        self,
        user_id: str,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        query: dict = {"user_id": user_id}
        if mode is not None:
            query["mode"] = mode
        if status is not None:
            query["status"] = status
        cursor = self.collection.find(query).sort("created_at", -1).limit(limit)
        return [_clean(doc) for doc in await cursor.to_list(length=None)]

    async def decide(
        self,
        user_id: str,
        suggestion_id: str,
        status: str,
        reason: Optional[str] = None,
        order_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Only a PENDING suggestion owned by this user can be decided, so a
        double-clicked Approve cannot place a second order and one account
        cannot act on another's inbox. Returns None when the guard bites."""
        result = await self.collection.find_one_and_update(
            {"user_id": user_id, "id": suggestion_id, "status": PENDING},
            {"$set": {
                "status": status,
                "reason": reason,
                "order_id": order_id,
                "decided_at": now or datetime.now(timezone.utc),
            }},
            return_document=True,
        )
        if result is None:
            return None
        decided = await self.get(user_id, suggestion_id)
        await hub.publish(user_id, "suggestions", "decided", decided)
        return decided

    async def settle(
        self, user_id: str, suggestion_id: str, status: str, **fields,
    ) -> Optional[dict]:
        """Ends an approve-live that decide() claimed as SENDING: EXECUTED
        or SENT once the broker has the order, back to PENDING if it never
        placed. Only a SENDING suggestion moves, so nothing else is undone."""
        result = await self.collection.find_one_and_update(
            {"user_id": user_id, "id": suggestion_id, "status": "SENDING"},
            {"$set": {"status": status, **fields}},
        )
        if result is None:
            return None
        settled = await self.get(user_id, suggestion_id)
        await hub.publish(user_id, "suggestions", "decided", settled)
        return settled

    async def attach_thesis(
        self, user_id: str, suggestion_id: str, thesis: Optional[str], score: Optional[dict] = None,
    ) -> None:
        """`score` replaces the stored one when research produced a real
        sentiment reading (backend/suggestions/thesis.py)."""
        changes = {}
        if thesis:
            changes["ai_thesis"] = thesis
        if score:
            changes["score"] = score
        if not changes:
            return
        await self.collection.update_one({"user_id": user_id, "id": suggestion_id}, {"$set": changes})
        await hub.publish(user_id, "suggestions", "enriched", await self.get(user_id, suggestion_id))

    async def expire_stale(self, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        result = await self.collection.update_many(
            {"status": PENDING, "expires_at": {"$lt": now}},
            {"$set": {"status": "EXPIRED", "decided_at": now}},
        )
        return result.modified_count


def _clean(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc
