"""/suggestions/* -- the approve/reject inbox.

Approving is the only place in the app where a human causes a trade, so the
guards matter more than the happy path: no double execution, no acting on
someone else's inbox, and an approval that actually reaches the ledger.
"""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.core.models import Intent, Order, Side
from backend.engine.persistence import LedgerStore
from backend.engine.runner import Proposal
from backend.routers import suggestions as suggestions_router
from backend.scoring.composite import CompositeScore
from backend.suggestions.store import SuggestionStore

_USER = User(
    id="alice", google_sub="sub-1", email="alice@example.com", name="Alice",
    picture=None, created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
)


def _proposal(symbol: str = "RELIANCE", mode: str = "LONGTERM") -> Proposal:
    return Proposal(
        order=Order(
            id="o-seed", symbol=symbol, side=Side.BUY, quantity=10.0,
            order_type="MARKET", limit_price=None, product="CNC",
        ),
        intent=Intent(
            symbol=symbol, side=Side.BUY, strength=0.9, reason_codes=["macd_cross"],
            stop_hint=90.0, target_hint=140.0,
        ),
        score=CompositeScore(rule_score=0.9, ai_score=0.2),
        entry=100.0,
        mode=mode,
    )


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


@pytest.fixture
def store(mongo):
    return SuggestionStore(mongo)


@pytest.fixture
def ledger(mongo):
    return LedgerStore(mongo, user_id="alice")


@pytest.fixture
def client(store, ledger):
    app = FastAPI()
    app.include_router(suggestions_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[suggestions_router.get_suggestion_store] = lambda: store
    app.dependency_overrides[suggestions_router.get_ledger_store] = lambda: ledger
    # No yfinance round trip in a unit test: approving fills at this price.
    app.dependency_overrides[suggestions_router.get_mark_price] = lambda: _fake_mark_price
    return TestClient(app)


async def _fake_mark_price(symbol: str) -> float:
    return 105.0


async def _seed(store, **overrides) -> dict:
    payload = dict(user_id="alice", proposal=_proposal(), source="scheduler")
    payload.update(overrides)
    return await store.create(**payload)


def test_list_returns_the_users_pending_inbox(client, store):
    import asyncio
    asyncio.run(_seed(store))
    asyncio.run(_seed(store, proposal=_proposal(symbol="TCS", mode="INTRADAY")))

    resp = client.get("/api/v1/suggestions", params={"mode": "LONGTERM"})

    assert resp.status_code == 200
    body = resp.json()
    assert [s["symbol"] for s in body] == ["RELIANCE"]
    assert body[0]["reason_codes"] == ["macd_cross"]
    assert body[0]["score"]["final"] > 0


def test_approve_places_the_order_and_opens_a_trade(client, store, ledger):
    import asyncio
    suggestion = asyncio.run(_seed(store))

    resp = client.post(f"/api/v1/suggestions/{suggestion['id']}/approve")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXECUTED"
    assert body["order_id"]

    trades = asyncio.run(ledger.get_trades())
    assert len(trades) == 1
    assert trades[0]["symbol"] == "RELIANCE"
    assert trades[0]["quantity"] == 10.0
    assert trades[0]["entry_price"] == 105.0, "fills at the current mark, not the stale reference"
    assert trades[0]["status"] == "OPEN"

    positions = asyncio.run(ledger.get_open_positions())
    assert positions["RELIANCE"].quantity == 10.0


def test_approving_twice_does_not_place_a_second_order(client, store, ledger):
    import asyncio
    suggestion = asyncio.run(_seed(store))

    first = client.post(f"/api/v1/suggestions/{suggestion['id']}/approve")
    second = client.post(f"/api/v1/suggestions/{suggestion['id']}/approve")

    assert first.status_code == 200
    assert second.status_code == 409
    assert len(asyncio.run(ledger.get_trades())) == 1


def test_reject_decides_without_touching_the_ledger(client, store, ledger):
    import asyncio
    suggestion = asyncio.run(_seed(store))

    resp = client.post(f"/api/v1/suggestions/{suggestion['id']}/reject", json={"reason": "too extended"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "REJECTED"
    assert resp.json()["reason"] == "too extended"
    assert asyncio.run(ledger.get_trades()) == []


def test_cannot_act_on_another_users_suggestion(client, store):
    import asyncio
    suggestion = asyncio.run(_seed(store, user_id="bob"))

    assert client.post(f"/api/v1/suggestions/{suggestion['id']}/approve").status_code == 404
    assert client.post(f"/api/v1/suggestions/{suggestion['id']}/reject").status_code == 404


def _option_proposal() -> Proposal:
    contract = {"strike": 2760.0, "expiry": "2026-10-27", "option_type": "PE", "lot_size": 250,
                "premium_estimate": 38.0, "premium_is_live": False, "margin_estimate": 1.0, "underlying_spot": 2905.0}
    return Proposal(
        order=Order(id="o-opt", symbol="RELIANCE26OCT2760PE", side=Side.SELL, quantity=250.0,
                    order_type="MARKET", limit_price=None, product="NRML"),
        intent=Intent(symbol="RELIANCE", side=Side.SELL, strength=0.9, reason_codes=["oversold_csp"],
                      option_flavor="CSP"),
        score=CompositeScore(rule_score=0.9, ai_score=0.0), entry=38.0, mode="LONGTERM",
        option_contract=contract,
    )


def test_approving_an_option_fills_at_its_live_premium_not_an_equity_mark(client, store, ledger):
    """An option's symbol is an NFO contract; pricing it as an NSE equity used
    to fail with "Unknown instrument", so option proposals could never fill."""
    import asyncio

    async def premium(user_id, symbol):
        assert (user_id, symbol) == ("alice", "RELIANCE26OCT2760PE")
        return 41.35

    async def no_equity_mark(symbol):
        raise AssertionError("an option must not be priced as an equity")

    client.app.dependency_overrides[suggestions_router.get_option_premium] = lambda: premium
    client.app.dependency_overrides[suggestions_router.get_mark_price] = lambda: no_equity_mark
    suggestion = asyncio.run(_seed(store, proposal=_option_proposal()))

    resp = client.post(f"/api/v1/suggestions/{suggestion['id']}/approve")

    assert resp.status_code == 200
    (fill,) = asyncio.run(ledger.get_fills())
    assert fill.symbol == "RELIANCE26OCT2760PE" and fill.price == 41.35


@pytest.mark.asyncio
async def test_an_option_cannot_fill_without_a_broker_to_price_it(mongo, monkeypatch):
    from fastapi import HTTPException

    from backend.instruments.master import InstrumentMaster
    from backend.instruments.models import Instrument

    await InstrumentMaster(mongo).upsert_many([Instrument(
        exchange="NFO", tradingsymbol="RELIANCE26OCT2760PE", name="RELIANCE", instrument_token=9,
        exchange_token=9, instrument_type="PE", segment="NFO-OPT", lot_size=250, tick_size=0.05,
        expiry=datetime(2026, 10, 27), strike=2760.0,
    )])
    monkeypatch.setattr(suggestions_router, "db", type("_Db", (), {"db": mongo, "redis": None})())
    monkeypatch.setattr(suggestions_router, "get_credential_store", lambda: None)

    async def nobody(*args):
        return None
    monkeypatch.setattr(suggestions_router, "live_premium_source", nobody)

    with pytest.raises(HTTPException) as caught:
        await suggestions_router._live_option_premium("alice", "RELIANCE26OCT2760PE")
    assert caught.value.status_code == 409
    assert "Connect Kite or Upstox" in caught.value.detail


# --- approve live: a real option order with the user's broker ---------------

class _FakeBroker:
    supports_options = True

    def __init__(self, statuses=("FILLED",), fail=None):
        self.statuses, self.fail, self.placed = list(statuses), fail, []

    async def place_order(self, order):
        if self.fail:
            raise RuntimeError(self.fail)
        self.placed.append(order)
        return "b-1"

    async def get_order_status(self, broker_order_id):
        from backend.core.models import BrokerOrderStatus
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        filled = 250.0 if status == "FILLED" else 0.0
        return BrokerOrderStatus(broker_order_id=broker_order_id, status=status,
                                 filled_quantity=filled, average_price=40.5 if filled else 0.0)


@pytest.fixture
def live_client(client, mongo, monkeypatch):
    import asyncio

    from backend.instruments.master import InstrumentMaster
    from backend.instruments.models import Instrument

    asyncio.run(InstrumentMaster(mongo).upsert_many([Instrument(
        exchange="NFO", tradingsymbol="RELIANCE26OCT2760PE", name="RELIANCE", instrument_token=9,
        exchange_token=9, instrument_type="PE", segment="NFO-OPT", lot_size=250, tick_size=0.05,
        expiry=datetime(2026, 10, 27), strike=2760.0,
    )]))
    monkeypatch.setattr(suggestions_router, "db", type("_Db", (), {"db": mongo, "redis": None})())
    # Live approvals need market hours: pin the clock to a Monday morning.
    monkeypatch.setattr(suggestions_router, "_now", lambda: datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc))
    return client


def _with_broker(client, broker):
    async def find(user_id):
        return broker
    client.app.dependency_overrides[suggestions_router.get_options_broker] = lambda: find


def test_approve_live_places_a_real_option_order_and_books_a_live_fill(live_client, store, ledger):
    import asyncio
    broker = _FakeBroker(statuses=("OPEN", "FILLED"))
    _with_broker(live_client, broker)
    suggestion = asyncio.run(_seed(store, proposal=_option_proposal()))

    resp = live_client.post(f"/api/v1/suggestions/{suggestion['id']}/approve-live")

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "EXECUTED" and resp.json()["venue"] == "live"
    (order,) = broker.placed
    assert order.contract.exchange == "NFO" and order.product == "NRML" and order.quantity == 250
    (fill,) = asyncio.run(ledger.get_fills())
    assert (fill.venue, fill.price, fill.quantity) == ("live", 40.5, 250.0)

    again = live_client.post(f"/api/v1/suggestions/{suggestion['id']}/approve-live")
    assert again.status_code == 409 and len(broker.placed) == 1


def test_approve_live_refused_by_the_broker_goes_back_to_pending(live_client, store, ledger):
    import asyncio
    _with_broker(live_client, _FakeBroker(fail="insufficient margin"))
    suggestion = asyncio.run(_seed(store, proposal=_option_proposal()))

    resp = live_client.post(f"/api/v1/suggestions/{suggestion['id']}/approve-live")

    assert resp.status_code == 502 and "insufficient margin" in resp.json()["detail"]
    assert asyncio.run(store.get("alice", suggestion["id"]))["status"] == "PENDING"
    assert asyncio.run(ledger.get_fills()) == []


def test_approve_live_needs_an_option_a_broker_and_no_kill_switch(live_client, store, mongo):
    import asyncio

    from backend.engine.session import IST
    from backend.risk.kill_switch import KillSwitchStore

    _with_broker(live_client, None)
    option = asyncio.run(_seed(store, proposal=_option_proposal()))
    resp = live_client.post(f"/api/v1/suggestions/{option['id']}/approve-live")
    assert resp.status_code == 409 and "Connect Kite or Upstox" in resp.json()["detail"]

    broker = _FakeBroker()
    _with_broker(live_client, broker)
    today = datetime.now(timezone.utc).astimezone(IST).date()
    asyncio.run(KillSwitchStore(mongo).trip("alice", today, reason="test", equity=-1.0))
    resp = live_client.post(f"/api/v1/suggestions/{option['id']}/approve-live")
    assert resp.status_code == 409 and "Daily loss limit" in resp.json()["detail"]
    assert broker.placed == []


# --- approve live: an equity proposal on the user's own account -------------

_OPEN = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)  # Monday 10:30 IST


class _FakeMine(_FakeBroker):
    async def get_order_status(self, broker_order_id):
        from backend.core.models import BrokerOrderStatus
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        filled = 10.0 if status == "FILLED" else 0.0
        return BrokerOrderStatus(broker_order_id=broker_order_id, status=status,
                                 filled_quantity=filled, average_price=105.5 if filled else 0.0)


@pytest.fixture
def mine_client(live_client, monkeypatch):
    from backend.suggestions import service
    monkeypatch.setattr(suggestions_router, "_now", lambda: _OPEN)
    monkeypatch.setattr(service, "LIVE_FILL_CHECKS", 1)
    return live_client


def _with_mine(client, broker):
    async def find(user_id):
        return broker
    client.app.dependency_overrides[suggestions_router.get_mine_broker] = lambda: find


def _approve_live(client, suggestion):
    return client.post(f"/api/v1/suggestions/{suggestion['id']}/approve-live")


def test_equity_approve_live_places_a_market_order_on_mine(mine_client, store, ledger):
    import asyncio
    broker = _FakeMine()
    _with_mine(mine_client, broker)
    suggestion = asyncio.run(_seed(store))
    resp = _approve_live(mine_client, suggestion)
    assert resp.status_code == 200, resp.text
    assert (resp.json()["status"], resp.json()["venue"]) == ("EXECUTED", "live")
    (order,) = broker.placed
    assert (order.order_type, order.product, order.quantity) == ("MARKET", "CNC", 10.0)


def test_intraday_equity_approve_live_is_mis(mine_client, store):
    import asyncio
    broker = _FakeMine()
    _with_mine(mine_client, broker)
    suggestion = asyncio.run(_seed(store, proposal=_proposal(mode="INTRADAY")))
    assert _approve_live(mine_client, suggestion).status_code == 200
    assert broker.placed[0].product == "MIS"


def test_equity_approve_live_not_filled_is_sent(mine_client, store):
    import asyncio
    _with_mine(mine_client, _FakeMine(statuses=("OPEN",)))
    suggestion = asyncio.run(_seed(store))
    assert _approve_live(mine_client, suggestion).json()["status"] == "SENT"


def test_equity_approve_live_rejected_goes_back_to_pending(mine_client, store):
    import asyncio
    _with_mine(mine_client, _FakeMine(statuses=("REJECTED",)))
    suggestion = asyncio.run(_seed(store))
    body = _approve_live(mine_client, suggestion).json()
    assert body["status"] == "PENDING" and body["reason"] == "Broker rejected the order"


@pytest.mark.parametrize("why", ["closed", "cap", "kill", "no_mine"])
def test_equity_approve_live_refusals_place_nothing(mine_client, store, mongo, monkeypatch, why):
    import asyncio

    from backend.engine.session import IST
    from backend.prefs import PrefsStore
    from backend.risk.kill_switch import KillSwitchStore

    broker = _FakeMine()
    _with_mine(mine_client, None if why == "no_mine" else broker)
    if why == "closed":
        monkeypatch.setattr(suggestions_router, "_now", lambda: datetime(2026, 10, 4, 5, 0, tzinfo=timezone.utc))
    if why == "cap":
        asyncio.run(PrefsStore(mongo).update("alice", {"per_trade_cap": 500.0}))
    if why == "kill":
        today = datetime.now(timezone.utc).astimezone(IST).date()
        asyncio.run(KillSwitchStore(mongo).trip("alice", today, reason="test", equity=-1.0))
    suggestion = asyncio.run(_seed(store))
    resp = _approve_live(mine_client, suggestion)
    assert resp.status_code == 409, resp.text
    assert broker.placed == []
    assert asyncio.run(store.get("alice", suggestion["id"]))["status"] == "PENDING"


def test_equity_approve_live_twice_places_one_order(mine_client, store):
    import asyncio
    broker = _FakeMine()
    _with_mine(mine_client, broker)
    suggestion = asyncio.run(_seed(store))
    assert _approve_live(mine_client, suggestion).status_code == 200
    assert _approve_live(mine_client, suggestion).status_code == 409
    assert len(broker.placed) == 1


def test_equity_sell_cannot_be_approved_with_real_money(mine_client, store, mongo):
    """A SELL proposal exits a paper position; approved live it would sell the
    user's own shares, which the paper position never bought."""
    import asyncio

    broker = _FakeMine()
    _with_mine(mine_client, broker)
    suggestion = asyncio.run(_seed(store))
    asyncio.run(mongo["suggestions"].update_one({"id": suggestion["id"]}, {"$set": {"side": "SELL"}}))
    resp = _approve_live(mine_client, suggestion)
    assert resp.status_code == 409 and "paper position" in resp.json()["detail"]
    assert broker.placed == []


def test_equity_broker_error_goes_back_to_pending(mine_client, store, ledger):
    import asyncio
    _with_mine(mine_client, _FakeMine(fail="insufficient margin"))
    suggestion = asyncio.run(_seed(store))
    resp = _approve_live(mine_client, suggestion)
    assert resp.status_code == 502 and "insufficient margin" in resp.json()["detail"]
    assert asyncio.run(store.get("alice", suggestion["id"]))["status"] == "PENDING"


def test_bookkeeping_failure_after_the_broker_took_it_is_not_pending(mine_client, store, ledger, monkeypatch):
    """Once place_order returned, a failed ledger write must not re-arm the
    button: a second tap would send a second real order."""
    import asyncio
    broker = _FakeMine()
    _with_mine(mine_client, broker)

    async def broken(order):
        raise RuntimeError("mongo timeout")

    monkeypatch.setattr(ledger, "record_order", broken)
    suggestion = asyncio.run(_seed(store))
    resp = _approve_live(mine_client, suggestion)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] in ("EXECUTED", "SENT")
    assert len(broker.placed) == 1



def test_an_option_cannot_be_approved_live_outside_market_hours(live_client, store, monkeypatch):
    import asyncio
    broker = _FakeBroker()
    _with_broker(live_client, broker)
    monkeypatch.setattr(suggestions_router, "_now", lambda: datetime(2026, 10, 4, 5, 0, tzinfo=timezone.utc))  # Sunday
    option = asyncio.run(_seed(store, proposal=_option_proposal()))
    resp = live_client.post(f"/api/v1/suggestions/{option['id']}/approve-live")
    assert resp.status_code == 409 and "market is closed" in resp.json()["detail"]
    assert broker.placed == []


def test_an_option_over_the_per_trade_cap_is_refused(live_client, store, mongo):
    import asyncio
    from backend.prefs import PrefsStore
    broker = _FakeBroker()
    _with_broker(live_client, broker)
    asyncio.run(PrefsStore(mongo).update("alice", {"per_trade_cap": 5_000.0}))
    proposal = _option_proposal()
    suggestion = asyncio.run(_seed(store, proposal=proposal))
    asyncio.run(mongo["suggestions"].update_one(
        {"id": suggestion["id"]}, {"$set": {"option_contract.margin_estimate": 80_000.0}}))
    resp = live_client.post(f"/api/v1/suggestions/{suggestion['id']}/approve-live")
    assert resp.status_code == 409 and "per-trade cap" in resp.json()["detail"]
    assert broker.placed == []
