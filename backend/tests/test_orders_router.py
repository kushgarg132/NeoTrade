"""/orders/*: the order ticket proposes a card (confirmed through
/chat/actions like any other), and lists or cancels open paper limits.
The AI account is not reachable from here."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.chat import actions
from backend.engine import paper_orders
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.prefs import PrefsStore
from backend.routers import orders

OPEN = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)  # Monday 10:30 IST


def _user(uid):
    return User(id=uid, google_sub=f"sub-{uid}", email=f"{uid}@example.com", name=uid,
                picture=None, created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))


@pytest.fixture
async def env(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    await InstrumentMaster(db).upsert_many([Instrument(
        exchange="NSE", tradingsymbol="INFY", name="INFOSYS", instrument_token=1, exchange_token=1,
        instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )])
    await PrefsStore(db).update("alice", {"per_trade_cap": 20000.0})

    async def mark(symbol):
        return 1500.0

    async def broker(user_id, credentials):
        return object()

    monkeypatch.setattr(actions, "_mark_price", mark)
    monkeypatch.setattr(actions, "_active_broker", broker)
    monkeypatch.setattr(actions, "_now", lambda: OPEN)
    monkeypatch.setattr(orders, "_db", lambda: db)
    app = FastAPI()
    app.include_router(orders.router)
    who = {"user": _user("alice")}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    return {"db": db, "client": TestClient(app), "who": who}


def _body(**over):
    body = {"symbol": "infy", "side": "BUY", "quantity": 2, "product": "CNC",
            "order_type": "LIMIT", "limit_price": 1490.0, "venue": "paper"}
    body.update(over)
    return body


def test_propose_paper_limit_returns_card(env):
    response = env["client"].post("/orders/propose", json=_body())
    assert response.status_code == 200
    card = response.json()
    assert card["summary"] == "BUY 2 INFY · delivery · limit ₹1,490.00 · ~₹2,980 on paper"
    assert card["needs_second_tap"] is False


def test_propose_live_card_needs_second_tap(env):
    card = env["client"].post("/orders/propose", json=_body(venue="live", order_type="MARKET", limit_price=None)).json()
    assert card["needs_second_tap"] is True
    assert card["summary"] == "BUY 2 INFY · delivery · market · ~₹3,000 on your account"


def test_limit_band_is_409(env):
    response = env["client"].post("/orders/propose", json=_body(limit_price=1801.0))
    assert response.status_code == 409 and "20%" in response.json()["detail"]


def test_account_field_is_422(env):
    assert env["client"].post("/orders/propose", json=_body(account="ai")).status_code == 422


def test_limit_without_price_is_422(env):
    assert env["client"].post("/orders/propose", json=_body(limit_price=None)).status_code == 422


async def test_paper_orders_list_and_cancel(env):
    placed = await paper_orders.place(env["db"], "alice", _body(symbol="INFY"), 1500.0, OPEN)
    listed = env["client"].get("/orders/paper").json()
    assert [o["id"] for o in listed] == [placed["id"]]
    assert env["client"].post(f"/orders/paper/{placed['id']}/cancel").status_code == 200
    assert env["client"].post(f"/orders/paper/{placed['id']}/cancel").status_code == 404


async def test_cannot_cancel_other_users_paper_order(env):
    placed = await paper_orders.place(env["db"], "bob", _body(symbol="INFY"), 1500.0, OPEN)
    assert env["client"].post(f"/orders/paper/{placed['id']}/cancel").status_code == 404


def test_limit_price_is_rounded_to_the_tick(env):
    card = env["client"].post("/orders/propose", json=_body(limit_price=1490.37)).json()
    assert "limit ₹1,490.35" in card["summary"]
