from datetime import datetime, timedelta, timezone

from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.datalayer import reactor
from backend.tests.test_datalayer_news import FakeRedis

NOW = datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc)
SECTORS = {"TCS": "Information Technology", "INFY": "Information Technology", "SBIN": "Financial Services"}


def _item(*impacts, **extra):
    return {"_id": "a1", "title": "T", "status": "SCORED", "material": True, "scored_at": NOW,
            "published_at": NOW - timedelta(minutes=20),
            "impacts": [dict(zip(("type", "target", "direction", "impact"), i)) for i in impacts], **extra}


def test_hits_follow_the_preference():
    item = _item(("symbol", "TCS", -0.8, 8), ("sector", "Information Technology", -0.5, 6),
                 ("symbol", "SBIN", 0.5, 4))
    targets = lambda pref, held, watched=(): {h["target"] for h in reactor.hits_for(item, SECTORS, pref, set(held), set(watched))}
    assert targets("held", {"TCS"}) == {"TCS"}
    assert targets("held", {"INFY"}) == {"INFY"}  # via its sector
    assert targets("held", set(), {"INFY"}) == set()  # watched only counts for held+watched
    assert targets("held+watched", set(), {"INFY"}) == {"INFY"}
    assert targets("held", {"SBIN"}) == set()  # impact 4 is below material
    assert targets("off", {"TCS"}) == set()
    assert targets("all", set()) == {"TCS", "Information Technology"}
    # a direct hit wins over the sector one
    [hit] = reactor.hits_for(item, SECTORS, "held", {"TCS"}, set())
    assert hit["impact"] == 8


def test_market_shock_reaches_anyone_holding_something():
    item = _item(("market", "INDIA", -0.9, 8))
    assert reactor.hits_for(item, SECTORS, "held", {"SBIN"}, set())[0]["target"] == "INDIA"
    assert reactor.hits_for(item, SECTORS, "held+watched", set(), {"SBIN"}) == []  # holds nothing
    assert reactor.hits_for(_item(("market", "INDIA", -0.9, 6)), SECTORS, "held", {"SBIN"}, set()) == []


@pytest.mark.asyncio
async def test_react_alerts_once(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = FakeRedis()
    sent = []

    async def deliver(db, redis, user_id, item, hits):
        sent.append((user_id, item["_id"], [h["target"] for h in hits]))

    async def followed(db):
        return {}, SECTORS

    monkeypatch.setattr(reactor, "_deliver", deliver)
    monkeypatch.setattr("backend.datalayer.news.followed", followed)
    await db["paper_positions"].insert_many([{"user_id": "u1", "symbol": "TCS.NS", "quantity": 5},
                                              {"user_id": "u2", "symbol": "TCS", "quantity": 0}])
    await db["user_prefs"].insert_one({"user_id": "u3", "news_alerts": "off"})
    await db["watchlist"].insert_one({"user_id": "u3", "symbols": ["TCS"]})
    await db["news_items"].insert_many([
        _item(("symbol", "TCS", -0.8, 8)),
        _item(("symbol", "TCS", -0.8, 8), _id="a2"),  # same target within the hour
        _item(("symbol", "TCS", -0.8, 8), _id="old", published_at=NOW - timedelta(hours=7)),
    ])

    assert await reactor.react(db, redis, NOW) == 1
    assert sent == [("u1", "a1", ["TCS"])]
    assert await reactor.react(db, redis, NOW) == 0  # claimed: never twice


def test_alert_text():
    text = reactor.alert_text({"title": "T", "event": "TCS cuts guidance", "url": "https://x"},
                              [{"target": "TCS", "direction": -0.8, "impact": 8.0}, {"target": "INDIA", "direction": -0.5, "impact": 7.0}])
    assert text == "📰 TCS cuts guidance\nTCS ↓ 8/10, Market ↓ 7/10\nhttps://x"


def test_scan_targets_direct_hits_first_then_the_sector():
    item = _item(("sector", "Information Technology", 0.6, 7), ("symbol", "TCS", 0.8, 8),
                 ("symbol", "SBIN", 0.5, 4), ("market", "INDIA", 0.9, 9))
    assert reactor.scan_targets(item, SECTORS, {"TCS", "INFY", "SBIN"}) == ["TCS", "INFY"]
    assert reactor.scan_targets(item, SECTORS, {"SBIN"}) == []  # below material; market moves no scan


@pytest.mark.asyncio
async def test_scan_once_per_user_and_symbol_a_day(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    redis = FakeRedis()
    scans = []

    async def scan_user(db, redis, prefs, symbols, now):
        scans.append((prefs["user_id"], symbols))
        return [{"id": "s1"}]

    async def followed(db):
        return {}, SECTORS

    async def users(self):
        return [{"user_id": "u1", "universe": ["TCS.NS", "INFY", "SBIN"]}]

    monkeypatch.setattr(reactor, "_scan_user", scan_user)
    monkeypatch.setattr("backend.datalayer.news.followed", followed)
    monkeypatch.setattr("backend.prefs.PrefsStore.scan_enabled_users", users)
    monkeypatch.setattr(reactor, "MAX_SCAN_SYMBOLS", 1)
    await db["news_items"].insert_one(_item(("sector", "Information Technology", 0.6, 7), ("symbol", "INFY", 0.8, 8)))

    assert await reactor.scan(db, redis, NOW) == 1
    assert scans == [("u1", ["INFY"])]  # capped at MAX_SCAN_SYMBOLS, direct hit first
    await db["news_items"].insert_one(_item(("symbol", "INFY", 0.8, 8), _id="a2"))
    assert await reactor.scan(db, redis, NOW) == 0  # INFY already scanned today


@pytest.mark.asyncio
async def test_news_proposals_go_to_the_autopilot_only_when_asked(monkeypatch):
    from backend.engine import autorun
    from backend.suggestions import notify as notify_module, scan as scan_module, thesis

    handed, told = [], []

    async def scan_universe(db, **kw):
        return [{"id": "s1", "symbol": "TCS"}]

    async def proposals(db, redis, store, user_id, pending, now, source="engine", heading=""):
        handed.append((user_id, source))
        return []

    async def notify(db, user_id, text):
        told.append(text)

    monkeypatch.setattr(scan_module, "scan_universe", scan_universe)
    monkeypatch.setattr(thesis, "attach_theses", AsyncMock())
    monkeypatch.setattr(autorun, "_autopilot_proposals", proposals)
    monkeypatch.setattr(notify_module, "notify", notify)
    prefs = {"user_id": "u1", "account_size": 1.0, "max_exposure": 1.0, "autopilot_enabled": True}

    await reactor._scan_user(AsyncMongoMockClient()["t"], None, prefs, ["TCS"], NOW)
    assert handed == [] and len(told) == 1  # autopilot_news off: a proposal to decide
    await reactor._scan_user(AsyncMongoMockClient()["t"], None, {**prefs, "autopilot_news": True}, ["TCS"], NOW)
    assert handed == [("u1", "news")] and len(told) == 1  # taken: nothing left to propose


@pytest.mark.asyncio
async def test_shadow_exits_log_and_place_nothing(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]

    async def followed(db):
        return {}, SECTORS

    monkeypatch.setattr("backend.datalayer.news.followed", followed)
    await db["user_prefs"].insert_one({"user_id": "u1", "autopilot_enabled": True, "autopilot_news": True})
    await db["paper_trades"].insert_one({"user_id": "u1", "symbol": "INFY", "side": "BUY", "quantity": 3,
                                   "status": "OPEN", "venue": "paper", "mode": "LONGTERM",
                                   "strategy": "autopilot:engine"})
    await db["news_items"].insert_many([
        _item(("sector", "Information Technology", -0.7, 8)),
        _item(("symbol", "INFY", -0.9, 9), _id="a2"),  # same symbol, same day: logged once
    ])
    assert await reactor.shadow_exits(db, FakeRedis(), NOW) == 1
    [row] = await db["autopilot_shadow"].find().to_list(length=None)
    assert (row["symbol"], row["side"], row["quantity"]) == ("INFY", "SELL", 3)
    assert await db["autopilot_log"].count_documents({}) == 0


def test_exit_hit_needs_a_big_negative_move():
    assert reactor.exit_hit(_item(("symbol", "INFY", -0.4, 9)), "INFY", SECTORS) is None
    assert reactor.exit_hit(_item(("symbol", "INFY", -0.9, 7)), "INFY", SECTORS) is None
    assert reactor.exit_hit(_item(("sector", "Information Technology", -0.6, 8)), "TCS", SECTORS)
