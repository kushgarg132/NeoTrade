from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.journal.insights import build_insights
from backend.journal.news import attach_news

T0 = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


def _trip(i, symbol="TCS", direction="LONG", pnl=-100.0, opened=T0, underlying=None):
    return {"id": str(i), "symbol": symbol, "underlying": underlying or symbol, "direction": direction, "pnl": pnl,
            "opened_at": opened + timedelta(days=i), "closed_at": opened + timedelta(days=i, hours=1),
            "quantity": 1, "entry_price": 100.0, "kind": "STOCK"}


def _news(_id, target, at, impact=8, direction=-0.7):
    return {"_id": _id, "status": "SCORED", "published_at": at,
            "impacts": [{"type": "symbol", "target": target, "impact": impact, "direction": direction}]}


async def test_attach_news_uses_the_underlying_and_the_24h_window(mongo):
    trips = [_trip(0, symbol="NIFTY24OCT25000CE", underlying="NIFTY"), _trip(1)]
    await mongo["news_items"].insert_many([
        _news("a", "NIFTY", T0 - timedelta(minutes=10)),
        _news("b", "TCS", T0 + timedelta(days=1) - timedelta(hours=30)),   # older than 24h before trip 1
    ])
    out = await attach_news(mongo, trips)
    assert out[0]["news"] == {"direction": -0.7, "impact": 8, "minutes_before": 10}
    assert out[1]["news"] is None


def test_against_news_and_chasing_news_findings():
    against = [{**_trip(i), "news": {"direction": -0.7, "impact": 8, "minutes_before": 60}} for i in range(5)]
    chasing = [{**_trip(10 + i, direction="SHORT", pnl=50.0),
                "news": {"direction": -0.7, "impact": 7, "minutes_before": 5}} for i in range(5)]
    quiet = [{**_trip(20 + i, pnl=20.0), "news": None} for i in range(5)]
    kinds = {f["kind"]: f for f in build_insights(against + chasing + quiet)}
    assert kinds["against_news"]["trips"] == 5 and kinds["against_news"]["title"] == "Traded against strong news"
    assert kinds["chasing_news"]["trips"] == 5
    assert kinds["chasing_news"]["title"] == "Entered within 15 minutes of big news"


def test_no_news_no_finding():
    kinds = {f["kind"] for f in build_insights([{**_trip(i), "news": None} for i in range(10)])}
    assert not kinds & {"against_news", "chasing_news"}
