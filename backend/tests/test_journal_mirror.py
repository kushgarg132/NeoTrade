"""The journal's mirrors: what charges took from the trader's real P&L, how
often they trade against SEBI's 500-trades-a-year line, and how they did
against simply holding the Nifty."""

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.journal import mirror
from backend.journal.roundtrips import build_round_trips

T0 = datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc)  # 09:30 IST


def _fill(i, symbol, side, qty, price, at, exchange="NSE"):
    return {"_id": f"t{i}", "broker": "upstox", "exchange": exchange, "symbol": symbol, "side": side,
            "quantity": qty, "price": price, "traded_at": at}


def _book():
    return [
        # Same-day stock round trip: intraday charges.
        _fill(1, "INFY", "BUY", 10, 1500.0, T0),
        _fill(2, "INFY", "SELL", 10, 1510.0, T0 + timedelta(hours=3)),
        # Held overnight: delivery charges (STT both sides).
        _fill(3, "TCS", "BUY", 5, 3000.0, T0),
        _fill(4, "TCS", "SELL", 5, 2990.0, T0 + timedelta(days=3)),
        # An option round trip.
        _fill(5, "NIFTY26SEP25000CE", "BUY", 75, 100.0, T0, exchange="NFO"),
        _fill(6, "NIFTY26SEP25000CE", "SELL", 75, 120.0, T0 + timedelta(hours=1), exchange="NFO"),
    ]


def test_cost_mirror_estimates_charges_by_product_and_nets_them():
    trades = _book()
    m = mirror.costs(trades, build_round_trips(trades), capital=100_000.0)
    by_product = m["charges_by_kind"]
    assert set(by_product) == {"intraday", "delivery", "options"}
    # Delivery pays STT on both legs, so it costs more than the intraday trip of similar size.
    assert by_product["delivery"] > by_product["intraday"]
    assert m["gross_pnl"] == pytest.approx(100.0 - 50.0 + 1500.0)
    assert m["net_pnl"] == pytest.approx(m["gross_pnl"] - m["charges"])
    assert m["charges_pct_of_capital"] == pytest.approx(m["charges"] / 100_000.0)
    assert m["fills"] == 6


def test_trade_rate_is_annualised_against_the_sebi_line():
    start = datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc)
    trades = [_fill(i, "INFY", "BUY" if i % 2 == 0 else "SELL", 1, 100.0, start + timedelta(days=i // 4))
              for i in range(400)]  # 400 fills over ~100 days
    m = mirror.costs(trades, build_round_trips(trades), capital=100_000.0)
    assert m["trades_per_year"] > mirror.SEBI_HEAVY_TRADER  # ~1,460 a year
    assert m["heavy_trader"] is True


def test_benchmark_mirror_compares_net_return_with_the_nifty():
    nifty = [(date(2026, 9, 1), 25000.0), (date(2026, 9, 15), 25500.0), (date(2026, 9, 30), 26000.0)]
    b = mirror.benchmark(net_pnl=-2000.0, capital=100_000.0, start=date(2026, 9, 1), end=date(2026, 9, 30),
                         nifty=nifty)
    assert b["your_return"] == pytest.approx(-0.02)
    assert b["nifty_return"] == pytest.approx(0.04)
    assert b["difference"] == pytest.approx(-0.06)
    assert mirror.benchmark(0.0, 100_000.0, date(2026, 9, 1), date(2026, 9, 30), nifty=[]) is None


def test_empty_journal_has_an_empty_mirror():
    assert mirror.costs([], [], capital=100_000.0)["fills"] == 0


def test_journal_endpoint_carries_the_mirror(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mongomock_motor import AsyncMongoMockClient

    from backend.auth.dependency import get_current_user
    from backend.auth.models import User
    from backend.journal.store import JournalStore
    from backend.routers import journal as journal_router

    mock_db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(journal_router.db, "db", mock_db)
    monkeypatch.setattr(journal_router.db, "redis", None)

    async def no_brokers(*_a):
        return []

    monkeypatch.setattr(journal_router, "connected_brokers", no_brokers)
    store = JournalStore(mock_db)
    import asyncio
    asyncio.run(mock_db["journal_trades"].insert_many([{**fill, "user_id": "alice"} for fill in _book()]))
    app = FastAPI()
    app.include_router(journal_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id="alice", google_sub="g", email="a@x.io", name="A", created_at=T0)
    app.dependency_overrides[journal_router.get_journal_store] = lambda: store
    app.dependency_overrides[journal_router.get_nifty] = lambda: [(date(2026, 9, 1), 25000.0), (date(2026, 9, 30), 25500.0)]

    body = TestClient(app).get("/api/v1/journal").json()
    assert body["mirror"]["costs"]["fills"] == 6
    assert body["mirror"]["benchmark"]["nifty_return"] == pytest.approx(0.02)


async def test_friday_mirror_is_sent_to_each_trader(monkeypatch):
    from mongomock_motor import AsyncMongoMockClient

    import backend.portfolio.service as service
    import backend.suggestions.notify as notify_module
    from backend import scheduler

    db = AsyncMongoMockClient()["test_db"]
    await db["journal_trades"].insert_many([{**f, "user_id": "alice"} for f in _book()])
    sent = []

    async def nifty():
        return [(date(2026, 9, 1), 25000.0), (date(2026, 9, 30), 25500.0)]

    async def notify(db, user_id, text):
        sent.append((user_id, text))
        return True

    monkeypatch.setattr(service, "_nifty", nifty)
    monkeypatch.setattr(notify_module, "notify", notify)

    assert await scheduler._weekly_mirrors(db) == 1
    assert sent[0][0] == "alice" and "after" in sent[0][1] and "Nifty +2.0%" in sent[0][1]
