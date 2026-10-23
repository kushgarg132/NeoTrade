"""/watchlist/details: prices from the ingest quote cache, Yahoo only for a miss."""

import json
from datetime import datetime, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.auth.models import User
from backend.database import db
from backend.routers import watchlist


class _Redis:
    async def mget(self, keys):
        return [json.dumps({"ltp": 110.0, "prev_close": 100.0, "at": 7.0}) if k == "quote:TCS" else None for k in keys]


async def test_details_read_the_quote_cache_and_fetch_only_misses(monkeypatch):
    mongo = AsyncMongoMockClient()["test_db"]
    await mongo["watchlist"].insert_one({"user_id": "u1", "symbols": ["TCS", "NOPE"]})
    await mongo["instruments"].insert_one({"exchange": "NSE", "tradingsymbol": "TCS", "name": "TATA CONSULTANCY"})
    monkeypatch.setattr(db, "db", mongo)
    monkeypatch.setattr(db, "redis", _Redis())
    asked = []

    async def fetch(symbol):
        asked.append(symbol)
        raise ValueError("unknown")

    monkeypatch.setattr(watchlist, "fetch_stock_info_logic", fetch)
    user = User(id="u1", google_sub="g", email="a@b.c", name="A", created_at=datetime.now(timezone.utc))
    rows = await watchlist.get_watchlist_details(user)
    assert rows[0] == {"symbol": "TCS", "name": "TATA CONSULTANCY", "current_price": 110.0, "previous_close": 100.0,
                       "day_change": 10.0, "day_change_percent": 10.0, "at": 7.0}
    assert rows[1] == {"symbol": "NOPE", "error": "Failed to fetch data"}
    assert asked == ["NOPE"]
