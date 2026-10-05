from datetime import date, datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.datalayer.catalysts import catalyst_map

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


def _item(i, published, impacts, status="SCORED"):
    return {"_id": str(i), "status": status, "published_at": published, "impacts": impacts}


def _sym(symbol, impact, direction):
    return {"type": "symbol", "target": symbol, "impact": impact, "direction": direction}


async def test_overnight_material_symbol_news_becomes_a_catalyst(mongo):
    await mongo["news_items"].insert_one(
        _item(1, datetime(2026, 10, 5, 20, 0, tzinfo=IST), [_sym("TCS", 8, 0.7)]))
    assert await catalyst_map(mongo, date(2026, 10, 6), date(2026, 10, 6)) == {"2026-10-06": {"TCS": 0.7}}


async def test_monday_reaches_back_to_friday_close(mongo):
    await mongo["news_items"].insert_one(
        _item(1, datetime(2026, 10, 10, 11, 0, tzinfo=IST), [_sym("TCS", 8, -0.5)]))  # Saturday
    assert await catalyst_map(mongo, date(2026, 10, 12), date(2026, 10, 12)) == {"2026-10-12": {"TCS": -0.5}}


async def test_ignores_weak_sector_and_after_open_items(mongo):
    await mongo["news_items"].insert_many([
        _item(1, datetime(2026, 10, 5, 20, 0, tzinfo=IST), [_sym("TCS", 5, 0.7)]),
        _item(2, datetime(2026, 10, 5, 20, 0, tzinfo=IST),
              [{"type": "sector", "target": "Information Technology", "impact": 9, "direction": 0.8}]),
        _item(3, datetime(2026, 10, 6, 9, 20, tzinfo=IST), [_sym("INFY", 9, 0.8)]),
        _item(4, datetime(2026, 10, 5, 21, 0, tzinfo=IST), [_sym("WIPRO", 9, 0.8)], status="TRIAGED"),
    ])
    assert await catalyst_map(mongo, date(2026, 10, 6), date(2026, 10, 6)) == {"2026-10-06": {}}


async def test_strongest_impact_wins_and_naive_time_is_utc(mongo):
    await mongo["news_items"].insert_many([
        _item(1, datetime(2026, 10, 5, 20, 0, tzinfo=IST), [_sym("INFY", 7, -0.4)]),
        _item(2, datetime(2026, 10, 5, 16, 0), [_sym("INFY", 9, 0.6)]),  # naive = UTC = 21:30 IST
    ])
    assert await catalyst_map(mongo, date(2026, 10, 6), date(2026, 10, 6)) == {"2026-10-06": {"INFY": 0.6}}


async def test_window_spans_several_weekdays_only(mongo):
    result = await catalyst_map(mongo, date(2026, 10, 9), date(2026, 10, 12))  # Fri..Mon
    assert list(result) == ["2026-10-09", "2026-10-12"]
