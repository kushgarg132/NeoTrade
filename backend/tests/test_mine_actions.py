""""Needs you" (mine/actions.py): ranked, stable ids, dismiss/snooze per user,
verdict gate, Jan–Mar harvest, stop/target alerts once, and its readers."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.engine.session import IST
from backend.mine import actions
from backend.suggestions import exits

NOW = datetime(2026, 10, 15, 10, 30, tzinfo=IST)
MARKS = {"A": 85.0, "B": 100.0, "C": 100.0}


def _h(symbol, qty=10, price=100.0):
    return {"symbol": symbol, "isin": symbol, "quantity": qty, "avg_price": price, "last_price": price,
            "close_price": price, "broker": "upstox", "kind": "STOCK"}


async def _seed(db, verdict=("HOLD", "HOLD")):
    await db["users"].insert_many([{"id": "alice", "role": "admin"}, {"id": "bob", "role": "user"}])
    await db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": {"upstox": "mine"}})
    await db["portfolio_snapshots"].insert_one({
        "user_id": "alice", "at": NOW - timedelta(hours=20),
        "raw_holdings": [_h("A"), _h("B"), _h("C")],
        "holdings": [{"symbol": "A", "previous_verdict": verdict[0], "verdict": verdict[1], "reason_codes": ["below_200dma"]}]})
    await db["holding_theses"].insert_one({"user_id": "alice", "symbol": "A", "stop": 90.0, "target": 150.0})
    await db["news_items"].insert_one({"title": "B cuts guidance", "url": "https://n/b", "published_at": NOW - timedelta(hours=3),
                                       "impacts": [{"target": "B", "direction": -0.7, "impact": 7.0}]})
    await db["corporate_events"].insert_one({"symbol": "C", "kind": "ex_dividend",
                                             "date": (NOW.date() + timedelta(days=3)).isoformat(), "amount": 5.0})


@pytest.fixture
async def db(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(exits, "mark_prices", AsyncMock(return_value=MARKS))
    return db


async def test_rank_order(db):
    await _seed(db)
    assert [a["kind"] for a in await actions.build(db, "alice", NOW, True)] == ["stop_hit", "bad_news", "ex_dividend"]


async def test_ids_stable_across_builds(db):
    await _seed(db)
    first = [a["id"] for a in await actions.build(db, "alice", NOW, True)]
    assert first == [a["id"] for a in await actions.build(db, "alice", NOW + timedelta(minutes=5), True)]
    assert first[0] == "stop_hit:A:90"


async def test_dismiss_hides_until_new_key(db):
    await _seed(db, ("HOLD", "SELL"))
    found = [a for a in await actions.build(db, "alice", NOW, True) if a["kind"] == "verdict_worse"]
    assert [a["id"] for a in found] == ["verdict_worse:A:HOLD>SELL"]
    await actions.dismiss(db, "alice", found[0]["id"])
    assert not [a for a in await actions.build(db, "alice", NOW, True) if a["kind"] == "verdict_worse"]
    # Later it improved to ADD, then fell to SELL again: something new happened.
    await db["portfolio_snapshots"].update_one({"user_id": "alice"}, {"$set": {"holdings.0.previous_verdict": "ADD"}})
    assert [a["id"] for a in await actions.build(db, "alice", NOW, True)
            if a["kind"] == "verdict_worse"] == ["verdict_worse:A:ADD>SELL"]


async def test_snooze_expires_after_7_days(db):
    await _seed(db)
    await actions.snooze(db, "alice", "stop_hit:A:90", NOW)
    assert "stop_hit:A:90" not in [a["id"] for a in await actions.build(db, "alice", NOW + timedelta(days=6), True)]
    assert "stop_hit:A:90" in [a["id"] for a in await actions.build(db, "alice", NOW + timedelta(days=7, minutes=1), True)]


async def test_verdict_items_hidden_without_visibility(db):
    await _seed(db, ("HOLD", "SELL"))
    assert "verdict_worse" in {a["kind"] for a in await actions.build(db, "alice", NOW, True)}
    assert "verdict_worse" not in {a["kind"] for a in await actions.build(db, "alice", NOW, False)}


async def test_harvest_only_jan_to_mar(db):
    await _seed(db)
    await db["journal_trades"].insert_one({"_id": "t1", "user_id": "alice", "broker": "upstox", "exchange": "NSE",
                                           "symbol": "A", "side": "BUY", "quantity": 10, "price": 120.0,
                                           "traded_at": datetime(2026, 6, 1, 5, 0, tzinfo=timezone.utc)})
    feb = datetime(2027, 2, 10, 10, 30, tzinfo=IST)
    # I6: a loss with no gain to offset saves nothing, so no "sell" nudge.
    assert not any(a["kind"] == "harvest" for a in await actions.build(db, "alice", feb, True))
    await db["journal_trades"].insert_many([
        {"_id": f"z{i}", "user_id": "alice", "broker": "upstox", "exchange": "NSE", "symbol": "Z", "side": side,
         "quantity": 1, "price": price, "traded_at": datetime(2026, m, 1, 5, 0, tzinfo=timezone.utc)}
        for i, (side, price, m) in enumerate([("BUY", 100.0, 5), ("SELL", 1100.0, 6)])])
    # I10: keyed on the FY, so a dismissal holds for the rest of the season.
    assert any(a["id"] == "harvest::2026" for a in await actions.build(db, "alice", feb, True))
    assert not any(a["kind"] == "harvest" for a in await actions.build(db, "alice", NOW, True))


async def test_dismissals_outlast_the_day(db, monkeypatch):
    """I10: overweight, idea_exit, ltcg_soon and add used to key on the date
    and come back the next morning."""
    from backend.portfolio import rebalance

    await _seed(db)
    await db["portfolio_snapshots"].update_one({"user_id": "alice"}, {"$set": {"holdings": [
        {"symbol": "A", "verdict": "HOLD", "reason_codes": ["overweight"], "weight_pct": 30.0},
        {"symbol": "B", "verdict": "ADD", "verdict_since": "2026-10-10", "reason_codes": []}]}})
    await db["paper_trades"].insert_one({"_id": "p1", "user_id": "alice:mine", "symbol": "B", "status": "OPEN",
                                         "quantity": 5, "alerted": ["target"]})
    await db["journal_trades"].insert_one({"_id": "c1", "user_id": "alice", "broker": "upstox", "symbol": "C",
                                           "side": "BUY", "quantity": 10, "price": 50.0,
                                           "traded_at": NOW - timedelta(days=350)})
    monkeypatch.setattr(rebalance, "target_gaps", lambda rows, targets: ({}, 0.0, None))
    monkeypatch.setattr(rebalance, "suggest", lambda row, gap, total: {"side": "BUY", "quantity": 3, "price": 100.0})
    kinds = ("overweight", "idea_exit", "ltcg_soon", "add")
    today = {a["kind"]: a["id"] for a in await actions.build(db, "alice", NOW, True) if a["kind"] in kinds}
    assert today == {"overweight": "overweight:A:limit", "idea_exit": "idea_exit:B:p1:target",
                     "ltcg_soon": f"ltcg_soon:C:{(NOW - timedelta(days=350)).date().isoformat()}",
                     "add": "add:B:2026-10-10"}
    for action_id in today.values():
        await actions.dismiss(db, "alice", action_id)
    tomorrow = NOW + timedelta(days=1)
    assert not [a for a in await actions.build(db, "alice", tomorrow, True) if a["kind"] in kinds]


class _Redis:
    def __init__(self):
        self.keys = set()

    async def set(self, key, value, nx=False, ex=None, px=None):
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True


async def test_level_alert_once(db):
    await _seed(db)
    redis = _Redis()
    first = await actions.level_alerts(db, redis, "alice", NOW)
    assert [a["id"] for a in first] == ["stop_hit:A:90"] and "A hit your stop" in actions.levels_text(first)
    assert await actions.level_alerts(db, redis, "alice", NOW + timedelta(minutes=15)) == []


def _client(monkeypatch, router_module, db, user_id):
    monkeypatch.setattr(router_module.db, "db", db)
    monkeypatch.setattr(router_module.db, "redis", None)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id=user_id, google_sub="g", email=f"{user_id}@x.io", name=user_id, created_at=NOW)
    return TestClient(app)


async def test_dismiss_other_users_id_is_scoped(db, monkeypatch):
    from backend.routers import mine as mine_router

    await _seed(db)
    bob = _client(monkeypatch, mine_router, db, "bob")
    assert bob.post("/api/v1/mine/actions/stop_hit:A:90/dismiss").status_code == 200
    assert "stop_hit:A:90" in [a["id"] for a in await actions.build(db, "alice", NOW, True)]
    assert await db[actions.STATE].find_one({"user_id": "bob", "action_id": "stop_hit:A:90"})


def test_today_mine_actions_top3_and_no_duplicate_holding_items(monkeypatch):
    import asyncio

    from backend.routers import today as today_router

    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(exits, "mark_prices", AsyncMock(return_value=MARKS))
    from backend.portfolio import service
    monkeypatch.setattr(service, "mark_prices", AsyncMock(return_value=MARKS))
    monkeypatch.setattr(service.bars, "prev_closes", AsyncMock(return_value={}))
    asyncio.run(_seed(db, ("HOLD", "SELL")))
    # /today reads the real clock: keep the news and the ex-date near it, not near NOW.
    real = datetime.now(timezone.utc)
    asyncio.run(db["news_items"].update_many({}, {"$set": {"published_at": real - timedelta(hours=3)}}))
    asyncio.run(db["corporate_events"].update_many(
        {}, {"$set": {"date": (real.astimezone(IST).date() + timedelta(days=3)).isoformat()}}))
    asyncio.run(db["paper_trades"].insert_one({"user_id": "alice:mine", "symbol": "B", "status": "OPEN",
                                               "quantity": 5, "alerted": ["target"]}))
    client = _client(monkeypatch, today_router, db, "alice")
    app = client.app

    async def states(user_id, brokers):
        return {b: "ACTIVE" for b in brokers}

    app.dependency_overrides[today_router.get_broker_states] = lambda: states
    body = client.get("/api/v1/today").json()
    assert not {"exit", "verdict", "proposal"} & {n["kind"] for n in body["needs_you"]}
    assert [a["kind"] for a in body["mine_actions"]] == ["stop_hit", "idea_exit", "verdict_worse"]
    assert body["mine_actions_total"] == 5  # + bad_news, ex_dividend


def test_postclose_text_lists_top_actions():
    from backend.portfolio import digest

    acts = [{"kind": k, "symbol": s, "title": t} for k, s, t in [
        ("stop_hit", "A", "A hit your stop ₹90.00"), ("bad_news", "B", "B: <cuts> guidance"),
        ("results_soon", "C", "C results on 2026-10-18"), ("ex_dividend", "D", "D goes ex-dividend")]]
    text = digest.postclose_text(None, {"mine": 0.0, "ai": 0.0}, [], acts)
    assert "Needs you (4)" in text and "A hit your stop" in text and "B: &lt;cuts&gt; guidance" in text
    assert "C results" in text and "D goes ex-dividend" not in text
    assert "A hit your stop" in digest.premarket_text(None, {}, 0, {}, None, acts)
