from datetime import date, datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.datalayer import worker
from backend.mine import events

TODAY = date(2026, 10, 15)


@pytest.fixture
def db():
    return AsyncMongoMockClient()["t"]


def _patch(monkeypatch, rows):
    calls = []

    def fake(ticker):
        calls.append(ticker)
        return rows.get(ticker, [])

    monkeypatch.setattr(events, "_fetch_sync", fake)
    return calls


async def test_refresh_once_a_day(db, monkeypatch):
    calls = _patch(monkeypatch, {"TCS.NS": [{"kind": "results", "date": "2026-10-20", "amount": None}]})
    assert await events.refresh(db, {"TCS"}, TODAY) == 1
    assert await events.refresh(db, {"TCS"}, TODAY) == 0
    assert calls == ["TCS.NS"]
    assert await db.corporate_events.count_documents({}) == 1


async def test_upcoming_window(db, monkeypatch):
    rows = [{"kind": "results", "date": (TODAY + timedelta(days=n)).isoformat(), "amount": None} for n in (7, 8)]
    _patch(monkeypatch, {"TCS.NS": rows})
    await events.refresh(db, {"TCS"}, TODAY)
    got = await events.upcoming(db, {"TCS"}, TODAY, 7)
    assert [e["date"] for e in got] == [(TODAY + timedelta(days=7)).isoformat()]


async def test_dividends_use_qty_on_ex_date(db, monkeypatch):
    ex = "2026-06-10"
    _patch(monkeypatch, {"TCS.NS": [{"kind": "ex_dividend", "date": ex, "amount": 10.0}]})
    await events.refresh(db, {"TCS"}, TODAY)

    def t(d, q):
        return {"symbol": "TCS", "side": "BUY", "quantity": q, "price": 100.0,
                "traded_at": datetime.fromisoformat(d).replace(tzinfo=timezone.utc)}

    out = await events.dividends_received(db, [t("2026-01-01", 10), t("2026-07-01", 5)], "TCS", TODAY)
    assert out == [{"date": ex, "per_share": 10.0, "qty": 10.0, "amount": 100.0}]


async def test_fetch_failure_skips_symbol(db, monkeypatch):
    def fake(ticker):
        if ticker == "BAD.NS":
            raise RuntimeError("boom")
        return [{"kind": "results", "date": "2026-10-20", "amount": None}]

    monkeypatch.setattr(events, "_fetch_sync", fake)
    assert await events.refresh(db, {"BAD", "TCS"}, TODAY) == 1


def test_worker_registers_corp_events():
    assert "corp_events" in [l.name for l in worker._loops()]


async def test_dividends_scale_journal_qty_by_split_ratio(db, monkeypatch):
    # yfinance amounts are split-adjusted; a 1:2 split the journal never saw doubles its quantity.
    _patch(monkeypatch, {"TCS.NS": [{"kind": "ex_dividend", "date": "2026-06-10", "amount": 5.0}]})
    await events.refresh(db, {"TCS"}, TODAY)
    buy = {"symbol": "TCS", "side": "BUY", "quantity": 10, "price": 100.0,
           "traded_at": datetime.fromisoformat("2026-01-01").replace(tzinfo=timezone.utc)}
    out = await events.dividends_received(db, [buy], "TCS", TODAY, ratio=2)
    assert out[0]["qty"] == 20 and out[0]["amount"] == 100.0


async def test_buy_blocked_fetches_an_unheld_symbol_and_respects_the_window(db, monkeypatch):
    calls = _patch(monkeypatch, {"TCS.NS": [{"kind": "results", "date": "2026-10-17", "amount": None}]})
    prefs = {"guardrails_enabled": True, "no_buy_before_results_days": 2}
    why = await events.buy_blocked(db, prefs, "TCS", TODAY)
    assert "in 2 days" in why and "2026-10-17" in why
    assert await events.buy_blocked(db, {**prefs, "no_buy_before_results_days": 1}, "TCS", TODAY) is None
    assert await events.buy_blocked(db, {**prefs, "no_buy_before_results_days": 0}, "INFY", TODAY) is None
    assert calls == ["TCS.NS"]  # fetched once that day; off never fetches
