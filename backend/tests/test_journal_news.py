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
    assert out[0]["news"] == {"direction": -0.7, "impact": 8, "minutes_before": 10, "headline": None, "url": None}
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


def test_a_put_bought_on_bad_news_trades_with_it_not_against_it():
    puts = [{**_trip(i, symbol="NIFTY24OCT25000PE", underlying="NIFTY"), "kind": "PUT",
             "news": {"direction": -0.8, "impact": 8, "minutes_before": 60}} for i in range(5)]
    calls = [{**_trip(10 + i, symbol="NIFTY24OCT25000CE", underlying="NIFTY"), "kind": "CALL",
              "news": {"direction": -0.8, "impact": 8, "minutes_before": 60}} for i in range(5)]
    against = {f["kind"]: f for f in build_insights(puts + calls)}["against_news"]
    assert against["trips"] == 5  # the calls, not the puts


async def test_attach_news_scales_with_a_long_journal(mongo):
    import time

    trips = [_trip(i % 300, symbol=f"S{i % 50}", opened=T0) for i in range(3000)]
    await mongo["news_items"].insert_many([_news(f"n{i}", f"S{i % 50}", T0 + timedelta(days=i % 300, minutes=-30))
                                           for i in range(3000)])
    began = time.monotonic()
    out = await attach_news(mongo, trips)
    assert time.monotonic() - began < 3.0
    assert all(t["news"] is not None for t in out)


async def test_attach_news_tags_the_exit_and_what_the_stock_did_next(mongo):
    from backend.datalayer.bars import today_ist

    today = today_ist()
    closed = datetime.combine(today - timedelta(days=10), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=6)
    trip = {**_trip(0), "opened_at": closed - timedelta(days=3), "closed_at": closed}
    await mongo["news_items"].insert_one({**_news("x", "TCS", closed - timedelta(hours=2), direction=-0.6),
                                          "title": "TCS cuts guidance", "url": "https://e.x/tcs"})
    # 100 on the exit day, then 5 bars later 110: +10%.
    days = [today - timedelta(days=d) for d in range(10, -1, -1)]
    await mongo["daily_bars"].insert_many([{"symbol": "TCS", "date": d.isoformat(), "close": 100.0 + 2 * i}
                                           for i, d in enumerate(days)])
    out = (await attach_news(mongo, [trip]))[0]
    assert out["news"] is None  # nothing in the 24h before entry
    assert out["exit_news"] == {"direction": -0.6, "impact": 8, "headline": "TCS cuts guidance",
                                "url": "https://e.x/tcs", "minutes_before": 120, "after_5d_pct": 10.0}


async def test_exit_news_without_bars_has_no_after_move(mongo):
    trip = _trip(0)
    await mongo["news_items"].insert_one(_news("x", "TCS", trip["closed_at"] - timedelta(minutes=30)))
    out = (await attach_news(mongo, [trip]))[0]
    assert out["exit_news"]["after_5d_pct"] is None


def _with(i, news=None, exit_news=None, pnl=-100.0, direction="LONG"):
    return {**_trip(i, pnl=pnl, direction=direction), "news": news, "exit_news": exit_news}


def test_bought_after_good_and_bad_news_findings():
    good = {"direction": 0.6, "impact": 7, "minutes_before": 120}
    bad = {"direction": -0.6, "impact": 7, "minutes_before": 120}
    trips = ([_with(i, news=good, pnl=200.0) for i in range(5)] + [_with(10 + i, news=bad) for i in range(5)]
             + [_with(20 + i, news=good, direction="SHORT") for i in range(5)] + [_with(30 + i) for i in range(4)])
    kinds = {f["kind"]: f for f in build_insights(trips)}
    assert kinds["bought_after_good_news"]["title"] == "Bought after good news"
    assert kinds["bought_after_good_news"]["trips"] == 5 and kinds["bought_after_good_news"]["pnl"] == 1000.0
    assert kinds["bought_after_bad_news"]["trips"] == 5 and kinds["bought_after_bad_news"]["pnl"] == -500.0
    assert "sold_after_bad_news" not in kinds


def test_sold_after_bad_news_reports_the_next_five_days_only_from_five_trips():
    def exit_bad(move):
        return {"direction": -0.7, "impact": 8, "minutes_before": 30, "after_5d_pct": move}
    four = [_with(i, exit_news=exit_bad(4.0)) for i in range(4)] + [_with(10 + i) for i in range(5)]
    assert "sold_after_bad_news" not in {f["kind"] for f in build_insights(four)}
    five = four + [_with(20, exit_news=exit_bad(None))]
    found = {f["kind"]: f for f in build_insights(five)}["sold_after_bad_news"]
    assert found["trips"] == 5 and found["title"] == "Sold after bad news"
    assert found["note"] == "In the 5 trading days after you sold, the stock moved +4.0% on average (4 of 5 with stored prices)"
    blind = [_with(i, exit_news=exit_bad(None)) for i in range(5)]
    assert "not shown" in {f["kind"]: f for f in build_insights(blind)}["sold_after_bad_news"]["note"]
