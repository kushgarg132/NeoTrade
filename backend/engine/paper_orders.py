"""Resting paper limit orders, placed from the order ticket.

A limit that can fill now fills now; otherwise it rests in `paper_orders`
until the mark crosses it (checked every minute in market hours) or the
session ends at 15:30, like a broker DAY order. A limit that fills on
placement is priced at the better of mark and limit (BUY min, SELL max); a
resting one fills at its limit. Fills are booked through
fill_on_paper, so charges match an engine fill. Each order is claimed
atomically before it fills, so two sweeps can never fill it twice.
"""

import asyncio
import logging
import uuid
from datetime import datetime, time
from typing import Awaitable, Callable

from pymongo import ReturnDocument

from backend.core.clock import SystemClock
from backend.core.models import Order, Side
from backend.engine.autorun import in_session
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST
from backend.suggestions.service import fill_on_paper

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 60
_CLOSE = time(15, 30)


def _collection(db):
    return db["paper_limit_orders"]  # its own collection: the ledger records its order in paper_orders with the same id


def _crossed(side: str, mark: float, limit: float) -> bool:
    return mark <= limit if side == "BUY" else mark >= limit


def _fill_price(side: str, mark: float, limit: float) -> float:
    return min(mark, limit) if side == "BUY" else max(mark, limit)


async def _held(db, user_id: str, symbol: str) -> float:
    position = (await LedgerStore(db, user_id=user_id).get_open_positions()).get(symbol)
    return position.quantity if position is not None else 0.0


async def _fill(db, doc: dict, price: float, now: datetime) -> float:
    order = Order(
        id=doc["id"], symbol=doc["symbol"], side=Side(doc["side"]), quantity=doc["quantity"],
        order_type="LIMIT", limit_price=doc["limit_price"], product=doc["product"], strategy_name="ticket",
    )
    await fill_on_paper(LedgerStore(db, user_id=doc["user_id"]), order, price, now)
    return price


async def place(db, user_id: str, params: dict, mark: float, now: datetime) -> dict:
    doc = {
        "id": str(uuid.uuid4()), "user_id": user_id, "symbol": params["symbol"], "side": params["side"],
        "quantity": params["quantity"], "product": params["product"], "limit_price": params["limit_price"],
        "status": "OPEN", "created_at": now, "filled_at": None, "fill_price": None,
        "session_date": now.astimezone(IST).date().isoformat(),
    }
    if _crossed(doc["side"], mark, doc["limit_price"]):
        price = _fill_price(doc["side"], mark, doc["limit_price"])
        doc.update(status="FILLED", filled_at=now, fill_price=await _fill(db, doc, price, now))
    await _collection(db).insert_one(dict(doc))
    return doc


async def sweep(db, mark_price: Callable[[str], Awaitable[float]], now: datetime) -> int:
    local = now.astimezone(IST)
    today = local.date().isoformat()
    changed = 0
    open_docs = await _collection(db).find({"status": "OPEN"}, {"_id": 0}).to_list(length=None)

    live = []
    for doc in open_docs:
        if doc["session_date"] < today or local.time() >= _CLOSE:
            result = await _collection(db).update_one(
                {"id": doc["id"], "status": "OPEN"}, {"$set": {"status": "EXPIRED"}}
            )
            changed += result.modified_count
        else:
            live.append(doc)
    if not live or not in_session(now):
        return changed

    marks = {}
    for symbol in {d["symbol"] for d in live}:
        try:
            marks[symbol] = await mark_price(symbol)
        except Exception as exc:
            logger.warning("paper orders: no mark for %s this pass: %s", symbol, exc)

    for doc in live:
        mark = marks.get(doc["symbol"])
        if mark is None or not _crossed(doc["side"], mark, doc["limit_price"]):
            continue
        claimed = await _collection(db).find_one_and_update(
            {"id": doc["id"], "status": "OPEN"}, {"$set": {"status": "FILLING", "claimed_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if claimed is None:
            continue
        if doc["side"] == "SELL" and doc["product"] == "CNC" and await _held(db, doc["user_id"], doc["symbol"]) < doc["quantity"]:
            await _collection(db).update_one(
                {"id": doc["id"]}, {"$set": {"status": "CANCELLED", "reason": "no longer held"}}
            )
            changed += 1
            continue
        try:
            # A resting limit fills at its limit: the mark is sampled once a
            # minute, so a fast move through it would flatter the paper book.
            price = await _fill(db, doc, doc["limit_price"], now)
        except Exception as exc:
            logger.exception("paper order %s fill failed: %s", doc["id"], exc)
            await _collection(db).update_one({"id": doc["id"]}, {"$set": {"status": "OPEN"}})
            continue
        await _collection(db).update_one(
            {"id": doc["id"]}, {"$set": {"status": "FILLED", "filled_at": now, "fill_price": price}}
        )
        changed += 1
    return changed


async def list_open(db, user_id: str) -> list[dict]:
    cursor = _collection(db).find({"user_id": user_id, "status": "OPEN"}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=None)


async def cancel(db, user_id: str, order_id: str) -> bool:
    result = await _collection(db).update_one(
        {"id": order_id, "user_id": user_id, "status": "OPEN"}, {"$set": {"status": "CANCELLED"}}
    )
    return result.modified_count == 1


async def _loop(db) -> None:
    from backend.chat.actions import _mark_price

    while True:
        try:
            now = SystemClock().now()
            await sweep(db, _mark_price, now)
            # Rows a crash left between claim and settle (engine/stuck.py).
            from backend.engine.stuck import sweep_stuck
            await sweep_stuck(db, now)
        except Exception as exc:
            logger.exception("paper order sweep failed: %s", exc)
        await asyncio.sleep(INTERVAL_SECONDS)


def start(db) -> asyncio.Task:
    return asyncio.create_task(_loop(db))
