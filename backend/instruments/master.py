import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

from backend.instruments.models import Instrument

# Writes in flight at once during a bulk upsert. Well under Motor's default
# pool of 100 connections, so other requests still get one meanwhile.
UPSERT_BATCH = 50

logger = logging.getLogger(__name__)


def _to_instrument(doc: dict) -> Instrument:
    doc = dict(doc)
    doc.pop("_id", None)
    return Instrument(**doc)


def _comparable(doc: dict) -> dict:
    """A row as stored vs. as fetched: Mongo hands datetimes back tz-aware
    (UTC), the broker dump has them naive."""
    return {k: v.replace(tzinfo=None) if isinstance(v, datetime) else v for k, v in doc.items()}


class InstrumentMaster:
    """Mongo-backed instrument master. Collection `instruments`, indexed on
    (exchange, tradingsymbol) unique and instrument_token unique."""

    def __init__(self, db):
        self.collection = db["instruments"]

    async def ensure_indexes(self):
        await self.collection.create_index([("exchange", 1), ("tradingsymbol", 1)], unique=True)
        await self.collection.create_index("instrument_token", unique=True)

    async def upsert_many(self, instruments: list[Instrument], only_new: bool = False) -> int:
        """Upserts by (exchange, tradingsymbol). Returns the count of documents
        actually inserted or changed (re-running with identical data is a no-op).
        `only_new` adds missing rows and leaves stored ones alone -- for the
        seed file and free lists, whose tokens are not a broker's.

        Concurrent rather than one round trip awaited at a time -- the free
        NSE/BSE sources (backend/instruments/free_source.py) upsert several
        thousand rows on every startup, and doing that serially measured
        150s. (bulk_write(UpdateOne(...)) would be the more obvious fix, but
        pymongo 4.18's UpdateOne unconditionally forwards a `sort` kwarg that
        the mongomock 4.3.0 fake this test suite runs against doesn't accept
        -- gather() on plain update_one calls gets the same real speedup
        without depending on bulk_write's newer wire format at all.)"""
        async def _upsert_one(instrument: Instrument) -> bool:
            result = await self.collection.update_one(
                {"exchange": instrument.exchange, "tradingsymbol": instrument.tradingsymbol},
                {"$set": instrument.model_dump()},
                upsert=True,
            )
            return result.upserted_id is not None or result.modified_count > 0

        # Every broker connect re-sends its whole dump (~60,000 rows for Kite
        # NSE+BSE+NFO), nearly all unchanged. One write per row held the Mongo
        # pool for minutes and every other request 504'd (2026-10-06), so read
        # what is stored in one pass and write only what differs.
        exchanges = sorted({i.exchange for i in instruments})
        stored = {(d["exchange"], d["tradingsymbol"]): _comparable(d)
                  async for d in self.collection.find({"exchange": {"$in": exchanges}}, {"_id": 0})}
        instruments = [i for i in instruments
                       if (i.exchange, i.tradingsymbol) not in stored
                       or not only_new and stored[(i.exchange, i.tradingsymbol)] != _comparable(i.model_dump())]

        # In batches: one gather() over a broker's full dump put every write
        # in flight at once and starved the event loop.
        changed = 0
        for start in range(0, len(instruments), UPSERT_BATCH):
            batch = instruments[start:start + UPSERT_BATCH]
            changed += sum(await asyncio.gather(*(_upsert_one(instrument) for instrument in batch)))
            await asyncio.sleep(0)  # let other requests run between batches
        return changed

    async def get(self, exchange: str, tradingsymbol: str) -> Optional[Instrument]:
        doc = await self.collection.find_one(
            {"exchange": exchange, "tradingsymbol": tradingsymbol.upper()}
        )
        return _to_instrument(doc) if doc else None

    async def get_by_token(self, token: int) -> Optional[Instrument]:
        doc = await self.collection.find_one({"instrument_token": token})
        return _to_instrument(doc) if doc else None

    async def option_contracts(self, underlying: str, option_type: str) -> list[Instrument]:
        """Every listed NFO contract of `option_type` (CE/PE) on `underlying`,
        as the connected broker's own instrument dump reported it, soonest
        expiry then lowest strike first. Real expiries, strikes and lot sizes,
        never computed."""
        cursor = self.collection.find({
            "exchange": "NFO", "name": underlying, "instrument_type": option_type,
            "expiry": {"$ne": None}, "strike": {"$ne": None},
        })
        contracts = [_to_instrument(doc) for doc in await cursor.to_list(length=None)]
        contracts.sort(key=lambda c: (c.expiry, c.strike))
        return contracts

    async def search(self, query: str, limit: int = 10) -> list[Instrument]:
        """Case-insensitive substring match against tradingsymbol/name. Exact
        tradingsymbol match (case-insensitive) is ranked first."""
        pattern = {"$regex": re.escape(query), "$options": "i"}
        cursor = self.collection.find(
            {"$or": [{"tradingsymbol": pattern}, {"name": pattern}]}
        ).limit(max(limit * 3, limit))
        docs = await cursor.to_list(length=None)
        instruments = [_to_instrument(doc) for doc in docs]

        query_upper = query.upper()
        instruments.sort(key=lambda inst: inst.tradingsymbol.upper() != query_upper)
        return instruments[:limit]
