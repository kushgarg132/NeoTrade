"""CAS PDF import: parser mocked (no real statement in the repo), user-scoped, nothing of the file kept."""

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.broker_credentials import get_credential_store
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.mine import cas_import
from backend.portfolio import service
from backend.routers import imports as imports_router

PDF = b"%PDF-1.7 synthetic"


def _cas():
    txn = NS(date=date(2025, 4, 1), type=NS(value="PURCHASE_SIP"), units=Decimal("10"), nav=Decimal("100"), amount=Decimal("1000"))
    one = NS(scheme="Alpha Fund", isin="INF000A00001", amfi="1", close=Decimal("10"), transactions=[txn],
             valuation=NS(nav=Decimal("120"), cost=Decimal("1000"), value=Decimal("1200")))
    two = NS(scheme="Alpha Fund", isin="INF000A00001", amfi="1", close=Decimal("10"), transactions=[],
             valuation=NS(nav=Decimal("120"), cost=None, value=Decimal("1200")))  # second folio, no cost
    gone = NS(scheme="Old Fund", isin="INF000B00002", amfi="2", close=Decimal("0"), transactions=[],
              valuation=NS(nav=Decimal("5"), cost=None, value=Decimal("0")))
    return NS(folios=[NS(folio="1", schemes=[one, gone]), NS(folio="2", schemes=[two])],
              statement_period=NS(from_="2025-01-01", to="2025-10-01"))


class _NoCreds:
    async def get(self, user_id, broker):
        return None


async def _no_nifty():
    return []


@pytest.fixture
def setup(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(imports_router.db, "db", db)
    monkeypatch.setattr(imports_router.db, "redis", None, raising=False)
    monkeypatch.setattr(service, "_nifty", _no_nifty)
    app = FastAPI()
    app.include_router(imports_router.router, prefix="/api/v1")
    holder = {"user": "alice"}
    app.dependency_overrides[get_current_user] = lambda: User(
        id=holder["user"], google_sub="g", email="a@x.io", name="A", created_at=datetime.now(timezone.utc))
    app.dependency_overrides[get_credential_store] = lambda: _NoCreds()
    return TestClient(app), db, holder


def _post(client, data=PDF, password="ABCDE1234F"):
    return client.post("/api/v1/imports/cas", files={"file": ("cas.pdf", data, "application/pdf")}, data={"password": password})


def test_from_cas_merges_folios_and_drops_zero_balance():
    holdings, txns, period = cas_import.from_cas(_cas())
    assert [h["isin"] for h in holdings] == ["INF000A00001"]
    h = holdings[0]
    assert h["kind"] == "MF" and h["broker"] == "cas" and h["quantity"] == 20
    assert h["avg_price"] == pytest.approx((1000 + 1200) / 20)  # no cost -> value, no invented gain
    assert h["last_price"] == 120 and len(txns) == 1 and txns[0]["type"] == "PURCHASE_SIP"
    assert period == {"from": "2025-01-01", "to": "2025-10-01"}


def test_import_stores_per_user_and_shows_in_the_snapshot(setup, monkeypatch):
    client, db, holder = setup
    monkeypatch.setattr(cas_import, "_read", lambda data, pw: _cas())
    res = _post(client)
    assert res.status_code == 200 and res.json()["funds"] == 1 and res.json()["transactions"] == 1
    doc = asyncio.run(db["portfolio_snapshots"].find_one({"user_id": "alice"}))
    assert [h["isin"] for h in doc["raw_holdings"]] == ["INF000A00001"]
    holder["user"] = "bob"
    assert client.get("/api/v1/imports").json()["funds"] == 0  # alice's import is not bob's
    holder["user"] = "alice"
    assert client.get("/api/v1/imports").json()["funds"] == 1


def test_wrong_password_nonpdf_and_oversize_are_422_and_leave_nothing(setup, monkeypatch):
    client, db, _ = setup

    class IncorrectPasswordError(Exception):
        pass

    def boom(data, pw):
        raise IncorrectPasswordError(f"bad {pw}")

    monkeypatch.setattr(cas_import, "_read", boom)
    res = _post(client, password="secret-pw")
    assert res.status_code == 422 and "secret-pw" not in res.text and "Wrong password" in res.text
    assert _post(client, data=b"not a pdf").status_code == 422
    assert _post(client, data=b"%PDF" + b"0" * (cas_import.MAX_BYTES + 1)).status_code == 422
    assert asyncio.run(db["mf_imports"].count_documents({})) == 0


def test_nsdl_statement_is_refused(setup, monkeypatch):
    client, _, _ = setup
    monkeypatch.setattr(cas_import, "_read", lambda d, p: NS(accounts=[]))
    res = _post(client)
    assert res.status_code == 422 and "NSDL" in res.json()["detail"]


def test_a_user_with_no_broker_and_no_import_gets_clean_empty_pages(setup, monkeypatch):
    from backend.routers import mine as mine_router

    client, db, _ = setup
    monkeypatch.setattr(mine_router.db, "db", db)
    client.app.include_router(mine_router.router, prefix="/api/v1")
    overview = client.get("/api/v1/mine/overview")
    assert overview.status_code == 200 and overview.json()["headline"] is None
    tax = client.get("/api/v1/mine/tax")
    assert tax.status_code == 200 and tax.json()["has_history"] is False
    assert client.get("/api/v1/mine/actions").status_code == 200


def test_delete_removes_funds_transactions_and_csv_fills_only_for_the_caller(setup, monkeypatch):
    client, db, _ = setup
    monkeypatch.setattr(cas_import, "_read", lambda data, pw: _cas())
    _post(client)
    asyncio.run(db["journal_trades"].insert_many([
        {"_id": "alice:kite:1", "user_id": "alice", "source": "console_csv", "traded_at": datetime(2025, 1, 1, tzinfo=timezone.utc)},
        {"_id": "alice:kite:2", "user_id": "alice", "source": "sync", "traded_at": datetime(2025, 1, 1, tzinfo=timezone.utc)},
        {"_id": "bob:kite:1", "user_id": "bob", "source": "console_csv", "traded_at": datetime(2025, 1, 1, tzinfo=timezone.utc)},
    ]))
    assert client.delete("/api/v1/imports").json() == {"transactions": 1, "trades": 1}
    assert asyncio.run(db["journal_trades"].count_documents({})) == 2
    assert client.get("/api/v1/imports").json()["funds"] == 0
    snaps = asyncio.run(db["portfolio_snapshots"].find({"user_id": "alice"}).sort("at", -1).to_list(length=1))
    assert snaps[0]["raw_holdings"] == []
