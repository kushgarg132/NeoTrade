"""The weekly report (reports/weekly.py): week parsing, each number from a
fixture, and the once-per-week Telegram send."""

from datetime import date, datetime, timedelta

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine.session import IST
from backend.reports import weekly

WEEK = "2026-W42"  # Mon 12 Oct - Sun 18 Oct 2026


def at(day, hour=11):
    return datetime(2026, 10, day, hour, 0, tzinfo=IST)


def test_week_parsing():
    assert weekly.parse_week("2026-W42") == date(2026, 10, 12)
    assert weekly.week_id(date(2026, 10, 18)) == "2026-W42"
    for bad in ("2026-42", "W42", "2026-W99", ""):
        with pytest.raises(ValueError):
            weekly.parse_week(bad)


def test_default_week_is_the_last_completed_one():
    assert weekly.last_completed(date(2026, 10, 19)) == "2026-W42"  # Monday
    assert weekly.last_completed(date(2026, 10, 14)) == "2026-W41"  # midweek
    assert weekly.last_completed(date(2026, 10, 18)) == "2026-W42"  # Sunday: the week just ended


def _trade(i, sym, side, price, when, qty=10):
    return {"_id": f"t{i}", "user_id": "u", "broker": "upstox", "exchange": "NSE", "symbol": sym, "side": side,
            "quantity": qty, "price": price, "traded_at": when}


@pytest.fixture
async def db():
    db = AsyncMongoMockClient()["t"]
    await db["user_prefs"].insert_one({"user_id": "u", "account_size": 100_000.0})
    await db["portfolio_snapshots"].insert_one({"user_id": "u", "at": at(9), "raw_holdings": []})
    # curve: Friday 9 Oct base, then two days in the week, with a 1000 deposit on Tuesday
    for d, value, nifty, flow in ((9, 10_000, 10_000, 0), (13, 11_000, 10_200, 1000), (16, 11_330, 10_400, 0),
                                  (19, 99_999, 99_999, 0)):
        await db["mine_daily"].insert_one({"user_id": "u", "date": f"2026-10-{d:02d}", "flow": flow, "invested": 0,
                                           "value": value, "nifty_value": nifty, "by_symbol": {}, "partial": False})
    await db["journal_trades"].insert_many([
        _trade(1, "WIN", "BUY", 100, at(12)), _trade(2, "WIN", "SELL", 120, at(14)),     # +200 gross
        _trade(3, "LOSE", "BUY", 100, at(13)), _trade(4, "LOSE", "SELL", 90, at(15)),    # -100 gross
        _trade(5, "OLD", "BUY", 100, at(1)), _trade(6, "OLD", "SELL", 150, at(5)),       # last month: out
    ])
    await db["paper_trades"].insert_many([
        {"user_id": "u", "venue": "paper", "status": "CLOSED", "exit_at": at(14), "realized_pnl": 1100.0, "costs": 100.0},
        {"user_id": "u", "venue": "paper", "status": "CLOSED", "exit_at": at(5), "realized_pnl": 9999.0, "costs": 0.0},
    ])
    for i, (sym, day, status, excess) in enumerate((("A", 12, "EXECUTED", 0.04), ("B", 13, "APPROVED", 0.02),
                                                    ("C", 14, "REJECTED", -0.01), ("D", 14, "PENDING", 0.5))):
        await db["suggestions"].insert_one({"user_id": "u", "id": f"s{i}", "symbol": sym, "status": status, "created_at": at(day, 9)})
        await db["forward_records"].insert_one({"_id": f"f{i}", "user_id": "u", "source": "suggestion", "symbol": sym,
                                                "decided_at": at(day, 9), "outcome": {"excess": excess}})
    return db


async def test_every_number(db):
    r = await weekly.build(db, "u", WEEK)
    assert r["week"] == WEEK
    assert r["you"]["ret"] == pytest.approx((11_330 - 10_000 - 1000) / 10_000)        # 0.033
    assert r["you"]["nifty"] == pytest.approx((10_400 - 10_000 - 1000) / 10_000)      # -0.06
    assert r["you"]["excess"] == pytest.approx(0.033 + 0.06)
    assert r["ai"]["ret"] == pytest.approx(0.01)                                       # (1100-100)/100k
    assert [b["symbol"] for b in r["best"]] == ["WIN"] and [w["symbol"] for w in r["worst"]] == ["LOSE"]
    assert r["ideas"]["taken"]["n"] == 2 and r["ideas"]["taken"]["mean_excess"] == pytest.approx(0.03)
    assert r["ideas"]["skipped"]["n"] == 1 and r["ideas"]["skipped"]["mean_excess"] == pytest.approx(-0.01)
    j = r["journal"]
    assert j["trades"] == 2 and j["charges"] > 0 and j["net"] == pytest.approx(100 - j["charges"], abs=0.01)


async def test_empty_week_has_none_not_zero(db):
    r = await weekly.build(db, "u", "2026-W30")
    assert r["you"]["ret"] is None and r["ai"]["ret"] == 0 and r["journal"]["trades"] == 0
    assert r["ideas"]["taken"] == {"n": 0, "mean_excess": None}
    assert "n/a" in weekly.text(r)


async def test_text_mirrors_the_report(db):
    t = weekly.text(await weekly.build(db, "u", WEEK))
    assert "2026-W42" in t and "+3.30%" in t and "WIN" in t and "LOSE" in t


class _Redis:
    def __init__(self):
        self.keys = set()

    async def set(self, key, value, nx=False, px=None):
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def delete(self, key):
        self.keys.discard(key)


async def test_send_once_per_user_per_week(db, monkeypatch):
    sent = []

    async def notify(db_, uid, text, html=False):
        sent.append((uid, text))

    monkeypatch.setattr("backend.suggestions.notify.notify", notify)
    redis = _Redis()
    assert await weekly.send(db, redis, at(18, 17)) == 0                 # Sunday 17:00: too early
    assert await weekly.send(db, redis, at(17, 19)) == 0                 # Saturday
    assert await weekly.send(db, redis, at(18, 18)) == 1
    assert await weekly.send(db, redis, at(18, 19)) == 0                 # once a week
    assert len(sent) == 1 and "2026-W42" in sent[0][1]
    assert "report:weekly:u:2026-W42" in redis.keys
    assert await weekly.send(db, redis, at(18, 18) + timedelta(days=7)) == 1  # next week sends again


async def test_a_failed_send_is_retried(db, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("telegram down")

    monkeypatch.setattr("backend.suggestions.notify.notify", boom)
    redis = _Redis()
    assert await weekly.send(db, redis, at(18, 18)) == 0
    assert not redis.keys
