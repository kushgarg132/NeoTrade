import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.datalayer import accuracy
from backend.tests.test_datalayer_news import FakeRedis

DAY = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)


def _row(day, direction, move, impact=6, scope="COMPANY", themes=("earnings",), **extra):
    return {"scope": scope, "themes": list(themes), "impact": impact, "direction": direction,
            "published_at": DAY + timedelta(days=day), "source": "Mint", "model": "m1", "move_5d": move, **extra}


def _cell(cells, **want):
    want = {"group": "theme", "key": "all", "impact": "all", "horizon": "5d", "measure": "move", **want}
    return next(c for c in cells if all(c[k] == v for k, v in want.items()))


def test_report_hit_rate_signed_mean_and_day_block_t():
    rows = [_row(0, 0.8, 0.02), _row(0, 0.8, 0.01), _row(1, -0.6, 0.01), _row(2, 0.9, 0.03, impact=8),
            _row(2, 0.3, -0.5)]  # too weak a direction to count
    cells = accuracy.report(rows)
    c = _cell(cells, scope="COMPANY")
    assert c["n"] == 4 and c["hit"] == 0.75 and c["thin"]
    assert c["mean"] == pytest.approx((0.02 + 0.01 - 0.01 + 0.03) / 4)  # move x sign(direction)
    assert c["t"] is not None and c["t"] > 0
    assert _cell(cells, scope="COMPANY", impact=">=7")["n"] == 1
    assert _cell(cells, scope="COMPANY", impact="5-7", key="earnings")["n"] == 3
    assert _cell(cells, group="source", key="Mint", scope="COMPANY")["n"] == 4
    assert _cell(cells, group="model", key="m1", scope="COMPANY")["n"] == 4
    assert not [x for x in cells if x["horizon"] == "1d"]  # no 1d moves, no 1d cells
    # One day only: no spread to bootstrap, so no t.
    assert _cell(accuracy.report(rows[:2]), scope="COMPANY")["t"] is None
    assert accuracy.impact_bucket(4.9) == "<5" and accuracy.impact_bucket(7) == ">=7"


def _report(n, hit, measure="move"):
    return {"cells": [{"group": "theme", "scope": "COMPANY", "key": "all", "impact": "all", "horizon": "5d",
                       "measure": measure, "n": n, "hit": hit}]}


def test_company_scan_ok_needs_the_bar_and_prefers_pre_move():
    assert accuracy.company_scan_ok(_report(300, 0.52))
    assert not accuracy.company_scan_ok(_report(299, 0.60))
    assert not accuracy.company_scan_ok(_report(500, 0.43))
    assert not accuracy.company_scan_ok(None) and not accuracy.company_scan_ok({"cells": []})
    both = {"cells": _report(400, 0.45, "pre_move")["cells"] + _report(400, 0.60)["cells"]}
    assert not accuracy.company_scan_ok(both)  # pre_move has enough rows: it decides
    few = {"cells": _report(100, 0.70, "pre_move")["cells"] + _report(400, 0.45)["cells"]}
    assert not accuracy.company_scan_ok(few)  # too few pre_move rows: falls back to move


@pytest.mark.asyncio
async def test_build_joins_item_source_and_model_and_runs_weekly():
    db, redis = AsyncMongoMockClient()["test_db"], FakeRedis()
    await db["news_items"].insert_one({"_id": "a", "source": "NSE filing", "model": "deep-1"})
    await db["news_outcomes"].insert_many([
        {"_id": "a:symbol:TCS", "item_id": "a", "scope": "COMPANY", "themes": ["orders"], "impact": 7,
         "direction": 0.7, "published_at": DAY, "move_5d": 0.02, "pre_move_5d": 0.03},
        {"_id": "b:symbol:TCS", "item_id": "b", "scope": "COMPANY", "themes": [], "impact": 7, "late": True,
         "direction": 0.7, "published_at": DAY, "move_5d": -0.02}])  # a biased base: left out
    await accuracy.loop(db, redis)
    doc = await db["news_accuracy"].find_one({"_id": "latest"})
    assert doc["rows"] == 1
    assert _cell(doc["cells"], group="source", key="NSE filing", scope="COMPANY")["n"] == 1
    assert _cell(doc["cells"], group="model", key="deep-1", scope="COMPANY", measure="pre_move")["mean"] == 0.03
    await db["news_accuracy"].delete_many({})
    await accuracy.loop(db, redis)  # not due again for a week
    assert await db["news_accuracy"].find_one({"_id": "latest"}) is None


def test_worker_registers_news_accuracy():
    from backend.datalayer import worker

    assert "news_accuracy" in [l.name for l in worker._loops()]


def test_endpoint_is_admin_only(monkeypatch):
    from backend.auth.dependency import get_current_user
    from backend.auth.models import User
    from backend.database import db as database
    from backend.routers import news

    mongo = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(database, "db", mongo)
    asyncio.run(mongo["news_accuracy"].insert_one({"_id": "latest", "as_of": DAY, "rows": 0, "cells": []}))
    app = FastAPI()
    app.include_router(news.router)
    client = TestClient(app)
    user = lambda role: User(id="u", google_sub="g", email="a@x.io", name="A", created_at=DAY, role=role)

    app.dependency_overrides[get_current_user] = lambda: user("user")
    assert client.get("/news/accuracy").status_code == 403
    app.dependency_overrides[get_current_user] = lambda: user("admin")
    body = client.get("/news/accuracy").json()
    assert body["cells"] == [] and body["company_scan_ok"] is False and "_id" not in body


async def test_build_computes_the_report_off_the_event_loop(monkeypatch):
    import threading

    seen = []
    monkeypatch.setattr(accuracy, "report", lambda rows: seen.append(threading.current_thread()) or [])
    await accuracy.build(AsyncMongoMockClient()["test_db"])
    assert seen and seen[0] is not threading.main_thread()
