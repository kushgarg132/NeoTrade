"""/watchlist/* -- always the signed-in user's own list.

The user id used to be a path parameter, which meant any account could read
or edit any other account's watchlist by guessing an id. It now comes from
the session token only.
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.datalayer.stock_info import fetch_stock_info_logic
from backend.core.models import Watchlist
from backend.database import db

router = APIRouter(prefix="/watchlist", tags=["Watchlist"])


async def _load_or_create(user_id: str) -> Watchlist:
    collection = db.db.watchlist
    doc = await collection.find_one({"user_id": user_id})
    if doc:
        doc.pop("_id", None)
        return Watchlist(**doc)

    # Upsert on the unique user_id index: two first requests can't both insert.
    watchlist = Watchlist(user_id=user_id, symbols=[])
    await collection.update_one({"user_id": user_id}, {"$setOnInsert": watchlist.model_dump()}, upsert=True)
    doc = await collection.find_one({"user_id": user_id})
    doc.pop("_id", None)
    return Watchlist(**doc)


@router.get("", response_model=Watchlist)
async def get_watchlist(user: User = Depends(get_current_user)):
    return await _load_or_create(user.id)


@router.post("/add", response_model=Watchlist)
async def add_to_watchlist(symbol: str = Query(max_length=30, pattern=r"^[A-Za-z0-9&._ -]+$"), user: User = Depends(get_current_user)):
    symbol = symbol.upper()
    watchlist = await _load_or_create(user.id)

    if symbol not in watchlist.symbols:
        await db.db.watchlist.update_one(
            {"user_id": user.id},
            {"$push": {"symbols": symbol}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        watchlist.symbols.append(symbol)

    return watchlist


@router.delete("/remove/{symbol}", response_model=Watchlist)
async def remove_from_watchlist(symbol: str, user: User = Depends(get_current_user)):
    await _load_or_create(user.id)
    await db.db.watchlist.update_one(
        {"user_id": user.id},
        {"$pull": {"symbols": symbol.upper()}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    return await _load_or_create(user.id)


@router.get("/details", response_model=List[Dict[str, Any]])
async def get_watchlist_details(user: User = Depends(get_current_user)):
    """Price, day change and `at` from the ingest quote cache (watched names are
    in its priority set), names from the instrument master; Yahoo only for a
    symbol the cache lacks. It used to be one Yahoo `info` call per symbol, in turn."""
    from backend.routers.market_data import _cached_quotes

    watchlist = await _load_or_create(user.id)
    bare = [s.upper().removesuffix(".NS") for s in watchlist.symbols]
    quotes = await _cached_quotes(bare)
    names = {d["tradingsymbol"]: d.get("name") async for d in db.db["instruments"].find(
        {"exchange": "NSE", "tradingsymbol": {"$in": bare}}, {"tradingsymbol": 1, "name": 1})}
    details = []
    for sym, b in zip(watchlist.symbols, bare):
        q = quotes.get(b)
        if q:
            prev = q["prev_close"]
            details.append({"symbol": sym, "name": names.get(b) or b, "current_price": q["price"], "previous_close": prev,
                            "day_change": q["price"] - prev if prev else None, "day_change_percent": q["change_pct"],
                            "at": q["at"]})
            continue
        try:
            info = await fetch_stock_info_logic(sym)
            details.append({**info.model_dump(), "at": time.time()})
        except Exception:
            details.append({"symbol": sym, "error": "Failed to fetch data"})
    return details
