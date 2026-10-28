import json
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.datalayer import outcomes
from backend.tests.test_datalayer_news import FakeRedis

NOW = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)  # 10:30 IST, in session
SECTORS = {"TCS": "IT", "INFY": "IT", "SBIN": "Banks"}


class Redis(FakeRedis):
    async def mget(self, keys):
        return [self.data.get(k) for k in keys]

    def prices(self, nifty, **quotes):
        self.data["macro:^NSEI"] = json.dumps({"value": nifty})
        for s, p in quotes.items():
            self.data[f"quote:{s}"] = json.dumps({"ltp": p})


def test_weights_need_samples_and_reward_hits():
    rows = [{"scope": "COMPANY", "themes": ["earnings"], "direction": 0.8, "move_1d": 0.02}] * 15 + \
           [{"scope": "COMPANY", "themes": ["earnings"], "direction": 0.8, "move_1d": -0.01}] * 5
    table = outcomes.compute_weights(rows)
    assert table["COMPANY|earnings|1"]["weight"] == 1.5 and table["COMPANY|earnings|1"]["n"] == 20
    assert outcomes.compute_weights(rows[:19]) == {}  # too few to trust
    noise = [{"scope": "MACRO", "themes": ["crude"], "direction": -0.5, "move_1d": 0.01}] * 20
    assert outcomes.compute_weights(noise)["MACRO|crude|-1"]["weight"] == 0.5
    weights = {"COMPANY|earnings|1": 1.5}
    assert outcomes.item_weight(weights, "COMPANY", ["earnings", "growth"], 0.3) == 1.5
    assert outcomes.item_weight(weights, "COMPANY", ["earnings"], -0.3) == 1.0  # other direction unknown


@pytest.mark.asyncio
async def test_record_then_measure_against_nifty(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = Redis()

    async def followed(db):
        return {}, SECTORS

    monkeypatch.setattr("backend.datalayer.news.followed", followed)
    await db["news_items"].insert_one({
        "_id": "a1", "title": "T", "status": "SCORED", "material": True, "scored_at": NOW,
        "published_at": NOW - timedelta(minutes=5), "scope": "COMPANY", "themes": ["earnings"],
        "impacts": [{"type": "symbol", "target": "TCS", "direction": 0.7, "impact": 7},
                    {"type": "sector", "target": "IT", "direction": 0.4, "impact": 6},
                    {"type": "market", "target": "INDIA", "direction": 0.2, "impact": 6}]})
    redis.prices(20000, TCS=100, INFY=200)
    assert await outcomes.record(db, redis, NOW) == 3
    assert await outcomes.record(db, redis, NOW) == 0  # claimed once

    redis.prices(20200, TCS=104, INFY=206)  # Nifty +1%, TCS +4%, INFY +3%
    assert await outcomes.measure(db, redis, NOW + timedelta(minutes=30)) == 0  # nothing due yet
    assert await outcomes.measure(db, redis, NOW + timedelta(hours=1)) == 3
    docs = {d["type"]: d async for d in db["news_outcomes"].find()}
    assert docs["symbol"]["move_1h"] == pytest.approx(0.03)
    assert docs["sector"]["move_1h"] == pytest.approx(0.025)
    assert docs["market"]["move_1h"] == pytest.approx(0.01)
    assert await outcomes.measure(db, redis, NOW + timedelta(hours=1)) == 0  # measured once
    assert await outcomes.measure(db, redis, NOW + timedelta(days=1)) == 3


@pytest.mark.asyncio
async def test_record_catches_up_old_items_after_an_outage(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = Redis()

    async def followed(db):
        return {}, SECTORS

    monkeypatch.setattr("backend.datalayer.news.followed", followed)
    await db["news_items"].insert_one({
        "_id": "old", "title": "T", "status": "SCORED", "material": True, "scored_at": NOW - timedelta(hours=20),
        "published_at": NOW - timedelta(hours=21), "scope": "COMPANY", "themes": ["earnings"],
        "impacts": [{"type": "symbol", "target": "TCS", "direction": 0.7, "impact": 7}]})
    redis.prices(20000, TCS=100)
    from backend.datalayer import reactor
    assert await reactor._claim(db, "reacted_at", NOW) == []  # too old for an alert
    assert await outcomes.record(db, redis, NOW) == 1  # but its outcome is still recorded
    assert await outcomes.record(db, redis, NOW) == 0  # once


async def _late_item(db, redis, monkeypatch):
    async def followed(db):
        return {}, SECTORS

    monkeypatch.setattr("backend.datalayer.news.followed", followed)
    await db["news_items"].insert_one({
        "_id": "old", "title": "T", "status": "SCORED", "material": True, "scored_at": NOW - timedelta(hours=20),
        "published_at": NOW - timedelta(hours=21), "scope": "COMPANY", "themes": ["earnings"],  # 13:30 IST the day before, before the close
        "impacts": [{"type": "symbol", "target": "TCS", "direction": 0.7, "impact": 7},
                    {"type": "market", "target": "INDIA", "direction": 0.2, "impact": 6}]})
    redis.prices(20500, TCS=110)


@pytest.mark.asyncio
async def test_late_item_is_priced_from_the_bars_at_publication(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = Redis()
    await _late_item(db, redis, monkeypatch)
    for symbol, close in (("TCS", 100.0), ("^NSEI", 20000.0)):
        await db["daily_bars"].insert_many([
            {"symbol": symbol, "date": "2026-10-02", "close": close - 5},
            {"symbol": symbol, "date": "2026-10-04", "close": close},  # that day's close came after publication: ignored
            {"symbol": symbol, "date": "2026-10-05", "close": close + 50}])  # after publication: ignored
    assert await outcomes.record(db, redis, NOW) == 2
    docs = {d["type"]: d async for d in db["news_outcomes"].find()}
    assert docs["symbol"]["base"] == {"TCS": 95.0} and docs["symbol"]["bench"] == 19995.0
    assert docs["market"]["bench"] == 19995.0 and not docs["symbol"].get("late")
    assert docs["symbol"]["in_session"] is False


@pytest.mark.asyncio
async def test_late_item_without_bars_is_flagged_and_kept_out_of_the_weights(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = Redis()
    await _late_item(db, redis, monkeypatch)
    assert await outcomes.record(db, redis, NOW) == 2
    docs = [d async for d in db["news_outcomes"].find()]
    assert all(d["late"] for d in docs) and docs[0]["bench"] == 20500

    rows = [{"scope": "COMPANY", "themes": ["earnings"], "direction": 0.8, "move_1d": 0.02, "late": True}] * 20
    assert outcomes.compute_weights(rows) == {}


@pytest.mark.asyncio
async def test_new_rows_measure_from_the_close_before_publication(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = Redis()

    async def followed(db):
        return {}, SECTORS

    monkeypatch.setattr("backend.datalayer.news.followed", followed)
    await db["news_items"].insert_one({
        "_id": "a1", "title": "T", "status": "SCORED", "material": True, "scored_at": NOW,
        "published_at": NOW - timedelta(minutes=5), "scope": "COMPANY", "themes": ["earnings"],  # 10:25 IST
        "impacts": [{"type": "symbol", "target": "TCS", "direction": 0.7, "impact": 7},
                    {"type": "market", "target": "INDIA", "direction": 0.2, "impact": 6}]})
    for symbol, pre, later in (("TCS", 95.0, 120.0), ("INFY", 190.0, 200.0), ("^NSEI", 19800.0, 21000.0)):
        await db["daily_bars"].insert_many([{"symbol": symbol, "date": "2026-10-04", "close": pre},
                                            {"symbol": symbol, "date": "2026-10-24", "close": later}])
    # An old row (before N0.2) is never given the new fields.
    await db["news_outcomes"].insert_one({"_id": "old", "type": "symbol", "target": "TCS", "base": {"TCS": 90.0},
                                          "bench": 19000.0, "base_at": NOW - timedelta(days=30), "move_1d": 0.01})
    redis.prices(20000, TCS=100, INFY=200)
    assert await outcomes.record(db, redis, NOW) == 2
    docs = {d["type"]: d async for d in db["news_outcomes"].find({"_id": {"$ne": "old"}})}
    sym, mkt = docs["symbol"], docs["market"]
    assert sym["base"] == {"TCS": 100} and sym["pre_base"] == {"TCS": 95.0} and sym["pre_bench"] == 19800.0
    assert sym["sector_pre_base"] == {"INFY": 190.0}  # its peers, not itself
    assert sym["moved_before"] == pytest.approx(100 / 95 - 20000 / 19800)  # already reacted before we scored
    assert mkt["moved_before"] == pytest.approx(20000 / 19800 - 1) and "sector_pre_base" not in mkt

    redis.prices(20200, TCS=104, INFY=206)
    assert await outcomes.measure(db, redis, NOW + timedelta(days=1)) == 2
    sym = await db["news_outcomes"].find_one({"type": "symbol", "_id": {"$ne": "old"}})
    assert sym["move_1d"] == pytest.approx(0.04 - 0.01)
    assert sym["pre_move_1d"] == pytest.approx(104 / 95 - 20200 / 19800)
    assert sym["sector_move_1d"] == pytest.approx(104 / 95 - 206 / 190)

    assert await outcomes.measure(db, redis, NOW + timedelta(days=20)) == 0  # the horizon bar may not be in yet
    assert await outcomes.measure(db, redis, NOW + timedelta(days=21, hours=1)) == 2  # 20d from closes
    sym = await db["news_outcomes"].find_one({"type": "symbol", "_id": {"$ne": "old"}})
    assert sym["move_20d"] == pytest.approx(0.2 - 0.05)
    assert sym["pre_move_20d"] == pytest.approx(120 / 95 - 21000 / 19800)
    assert sym["sector_move_20d"] == pytest.approx(120 / 95 - 200 / 190)
    assert await outcomes.measure(db, redis, NOW + timedelta(days=22)) == 0  # once
    assert "move_20d" not in await db["news_outcomes"].find_one({"_id": "old"})


@pytest.mark.asyncio
async def test_a_horizon_with_no_session_inside_it_is_unmeasured_not_a_miss(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = Redis()
    friday_evening = datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)  # 18:30 IST; +1d is Saturday
    redis.prices(20000, TCS=100)
    await db["news_outcomes"].insert_one({
        "_id": "a1:symbol:TCS", "type": "symbol", "target": "TCS", "base": {"TCS": 100.0}, "bench": 20000.0,
        "base_at": friday_evening, "in_session": False})
    assert await outcomes.measure(db, redis, friday_evening + timedelta(days=1)) == 1
    doc = await db["news_outcomes"].find_one({"_id": "a1:symbol:TCS"})
    assert doc["move_1d"] is None and doc["ret_1d"] is None
    assert outcomes.compute_weights([{**doc, "scope": "X", "themes": ["t"], "direction": 0.5}] * 20) == {}
