"""What news moved your money (portfolio/news_moves.py): big day moves matched to the news
before them, the weekly attribution, themes and the accuracy line, scoped to the user's own account."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine.session import IST
from backend.portfolio import digest, news_moves, service

NOW = datetime(2026, 10, 15, 15, 45, tzinfo=IST)  # Thursday after the close
SECTORS = {"BANKA": "Banks", "BANKB": "Banks", "IT1": "IT"}


def _item(title, impacts, at, themes=("results",), status="SCORED", material=True):
    return {"title": title, "url": f"https://x/{title}", "published_at": at, "status": status, "material": material,
            "themes": list(themes), "impacts": impacts}


def test_big_moves_take_beyond_two_pct_vs_nifty_or_the_top_rupee_movers():
    rows = [{"symbol": "A", "move_pct": -1.0, "rupees": -5000}, {"symbol": "B", "move_pct": 4.0, "rupees": 100},
            {"symbol": "C", "move_pct": -1.2, "rupees": -10}, {"symbol": "D", "move_pct": 0.5, "rupees": 4}]
    picked = news_moves.big_moves(rows, -1.0, top=1)
    assert [r["symbol"] for r in picked] == ["A", "B"]           # A by rupees, B +5% vs NIFTY; C is the market
    assert picked[1]["vs_nifty"] == 5.0
    assert [r["symbol"] for r in news_moves.big_moves(rows, None, top=0)] == ["B"]  # no NIFTY: the raw move


def test_cause_is_the_strongest_material_company_or_sector_item():
    items = [_item("weak", [{"type": "symbol", "target": "BANKA", "direction": 1, "impact": 5}], NOW),
             _item("sector", [{"type": "sector", "target": "Banks", "direction": -0.6, "impact": 7}], NOW),
             _item("company", [{"type": "symbol", "target": "BANKA", "direction": -0.8, "impact": 7}], NOW),
             _item("other", [{"type": "symbol", "target": "IT1", "direction": 1, "impact": 9}], NOW)]
    out = news_moves.attribute([{"symbol": "BANKA", "move_pct": -4.0, "rupees": -400},
                                {"symbol": "BANKB", "move_pct": -3.0, "rupees": -300},
                                {"symbol": "IT1", "move_pct": 0.1, "rupees": 1}], 0.0, items[:3], SECTORS)
    assert out[0]["cause"] == {"title": "company", "url": "https://x/company", "scope": "COMPANY",
                               "direction": -0.8, "impact": 7}   # a company item wins the tie
    assert out[1]["cause"]["title"] == "sector" and out[1]["cause"]["scope"] == "SECTOR"
    assert out[2]["cause"] is None and digest.news_why(out[2]) == "moved with the market"
    assert digest.news_why({"cause": None, "vs_nifty": -5.0}) == "no news found"


def test_themes_and_accuracy_line():
    items = [_item("a", [{"type": "symbol", "target": "BANKA", "direction": -1, "impact": 8}], NOW, ("results", "rates")),
             _item("b", [{"type": "sector", "target": "Banks", "direction": 1, "impact": 6}], NOW, ("rates",)),
             _item("c", [{"type": "symbol", "target": "ZZZ", "direction": 1, "impact": 9}], NOW, ("merger",))]
    assert news_moves.themes(items, {"BANKA"}, SECTORS) == [
        {"theme": "rates", "n": 2, "impact": 14.0, "direction": 0.0},
        {"theme": "results", "n": 1, "impact": 8.0, "direction": -1.0}]
    doc = {"cells": [{"scope": "COMPANY", "horizon": "5d", "measure": "raw", "hit": 0.5, "n": 10},
                     {"scope": "COMPANY", "horizon": "5d", "measure": "excess", "hit": 0.42, "n": 765},
                     {"scope": "SECTOR", "horizon": "5d", "measure": "excess", "hit": 65, "n": 257},
                     {"scope": "MARKET", "horizon": "5d", "measure": "excess", "hit": 0.59, "n": 596}]}
    assert news_moves.accuracy_line(doc) == {"company": {"hit_pct": 42.0, "n": 765}, "sector": {"hit_pct": 65.0, "n": 257}}
    assert news_moves.accuracy_line(None) is None and news_moves.accuracy_line({"cells": []}) is None


@pytest.fixture
async def db(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    await db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": {"upstox": "mine", "kite": "ai"}})
    holding = lambda s, b: {"symbol": s, "isin": s, "quantity": 10, "avg_price": 100.0, "last_price": 100.0,  # noqa: E731
                            "close_price": 100.0, "broker": b, "kind": "STOCK"}
    await db["portfolio_snapshots"].insert_one({"user_id": "alice", "at": NOW - timedelta(days=1), "holdings": [],
                                                "raw_holdings": [holding("BANKA", "upstox"), holding("IT1", "upstox"),
                                                                 holding("AIONLY", "kite")]})
    await db["news_items"].insert_many([
        _item("BANKA <fraud>", [{"type": "symbol", "target": "BANKA", "direction": -0.9, "impact": 9}],
              NOW - timedelta(hours=20)),                                     # after Wednesday's close
        _item("too old", [{"type": "symbol", "target": "IT1", "direction": 1, "impact": 9}], NOW - timedelta(days=3)),
        _item("AI only", [{"type": "symbol", "target": "AIONLY", "direction": 1, "impact": 9}], NOW - timedelta(hours=1)),
        _item("unscored", [{"type": "symbol", "target": "IT1", "direction": 1, "impact": 9}], NOW, status="TRIAGED")])
    monkeypatch.setattr(news_moves, "_nifty_day_pct", AsyncMock(return_value=-0.5))
    monkeypatch.setattr("backend.datalayer.news_sources.nifty200_sectors", lambda: SECTORS)
    monkeypatch.setattr(service, "mark_prices", AsyncMock(return_value={"BANKA": 90.0, "IT1": 103.0, "AIONLY": 150.0}))
    monkeypatch.setattr(service.bars, "prev_closes", AsyncMock(return_value={"BANKA": 100.0, "IT1": 100.0, "AIONLY": 100.0}))
    return db


async def test_pulse_lists_the_users_own_big_moves_with_the_news_before_them(db):
    p = await digest.pulse(db, "alice", NOW)
    moved = {m["symbol"]: m for m in p["news_moves"]}
    assert set(moved) == {"BANKA", "IT1"}                                    # never the AI account's stock
    assert moved["BANKA"]["cause"]["title"] == "BANKA <fraud>" and moved["BANKA"]["rupees"] == -100
    assert moved["IT1"]["cause"] is None and moved["IT1"]["vs_nifty"] == 3.5  # old and unscored items do not count
    text = digest.postclose_text(p, {"mine": 0.0, "ai": 0.0}, [])
    assert "What moved your money:" in text and "BANKA -10.0% — BANKA &lt;fraud&gt;" in text
    assert "IT1 +3.0% — no news found" in text


async def test_pulse_survives_a_news_failure(db, monkeypatch):
    monkeypatch.setattr(news_moves, "today", AsyncMock(side_effect=RuntimeError("mongo")))
    assert (await digest.pulse(db, "alice", NOW))["news_moves"] == []


async def test_week_attributes_big_weekly_movers_and_reads_the_latest_accuracy(db, monkeypatch):
    closes = {"2026-10-12": {"BANKA": 100.0, "IT1": 100.0, "^NSEI": 100.0},   # before Monday
              "2026-10-19": {"BANKA": 90.0, "IT1": 101.0, "^NSEI": 99.0}}     # Friday's close
    monkeypatch.setattr("backend.datalayer.bars.prev_closes", AsyncMock(side_effect=lambda db_, names, day: {
        s: c for s, c in closes[day.isoformat()].items() if s in names}))
    await db["news_accuracy"].insert_many([
        {"at": NOW - timedelta(days=8), "cells": [{"scope": "COMPANY", "horizon": "5d", "hit": 0.9, "n": 1}]},
        {"at": NOW, "cells": [{"scope": "COMPANY", "horizon": "5d", "hit": 0.42, "n": 765}]}])
    start = datetime(2026, 10, 12, tzinfo=IST)
    week = await news_moves.week(db, "alice", start, start + timedelta(days=7))
    assert [m["symbol"] for m in week["movers"]] == ["BANKA"]               # IT1 +2% vs NIFTY is not big
    assert week["movers"][0]["vs_nifty"] == -9.0 and week["movers"][0]["items"][0]["title"] == "BANKA <fraud>"
    assert week["themes"] == [{"theme": "results", "n": 2, "impact": 18.0, "direction": 0.05}]  # Monday's IT1 item too
    assert week["accuracy"] == {"company": {"hit_pct": 42.0, "n": 765}}
    await db["news_accuracy"].delete_many({})
    assert (await news_moves.week(db, "alice", start, start + timedelta(days=7)))["accuracy"] is None


def test_weekly_narrative_gets_the_news_as_facts():
    from backend.summaries.weekly import news_facts

    r = {"news": {"movers": [{"symbol": "BANKA", "move_pct": -10.0, "vs_nifty": -9.0, "items": [
        {"title": "fraud", "url": "u", "scope": "COMPANY", "direction": -0.9, "impact": 9}]}],
        "themes": [{"theme": "results", "n": 1, "impact": 9.0, "direction": -0.9}],
        "accuracy": {"company": {"hit_pct": 42.0, "n": 765}}}}
    f = news_facts(r)
    assert f["big_movers"] == [{"symbol": "BANKA", "move_pct": -10.0, "vs_nifty_pct": -9.0,
                                "news": [{"title": "fraud", "scope": "COMPANY", "direction": -0.9}]}]
    assert f["accuracy_5d_hit_pct"]["company"]["hit_pct"] == 42.0
    assert news_facts({}) == {"big_movers": [], "themes": [], "accuracy_5d_hit_pct": None}  # an older report
