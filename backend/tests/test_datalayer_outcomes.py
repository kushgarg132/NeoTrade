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
