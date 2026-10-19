"""GET /today: one call for the Today page -- what needs the user, whose
money is where, and how far setup has got. Each part fails on its own."""

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.routers import today as today_router

NOW = datetime.now(timezone.utc)
# Today's IST midnight: trades placed just after it are "today" at any hour the suite runs.
from backend.engine.session import IST  # noqa: E402
DAY = datetime.combine(NOW.astimezone(IST).date(), datetime.min.time(), tzinfo=IST)


def _client(monkeypatch, states=None, broken=False, role="user"):
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(today_router.db, "db", db)
    monkeypatch.setattr(today_router.db, "redis", None)

    async def broker_states(user_id, brokers):
        if broken:
            raise RuntimeError("broker API down")
        return {b: (states or {}).get(b, "NEEDS_LOGIN") for b in brokers}

    app = FastAPI()
    app.include_router(today_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id="alice", google_sub="g", email="a@x.io", name="A", created_at=NOW, role=role)
    app.dependency_overrides[today_router.get_broker_states] = lambda: broker_states
    return TestClient(app), db


def _seed(db, **docs):
    for collection, rows in docs.items():
        asyncio.run(db[collection].insert_many(rows))


def test_fresh_user_has_an_empty_setup_and_no_login_nags(monkeypatch):
    client, _ = _client(monkeypatch)
    body = client.get("/api/v1/today").json()
    assert body["setup"]["done"] == 0 and body["setup"]["total"] == 8
    assert not [n for n in body["needs_you"] if n["kind"] == "login"]
    assert body["accounts"] == {}


def test_login_needed_for_a_role_whose_broker_is_logged_out(monkeypatch):
    client, db = _client(monkeypatch, states={"upstox": "ACTIVE"})
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"kite": "ai", "upstox": "mine"}}])
    body = client.get("/api/v1/today").json()
    logins = [n for n in body["needs_you"] if n["kind"] == "login"]
    assert len(logins) == 1 and logins[0]["link"] == "/settings?tab=accounts" and "Kite" in logins[0]["title"]
    assert body["accounts"]["ai"] == {"broker": "kite", "state": "NEEDS_LOGIN"}
    assert body["accounts"]["mine"]["state"] == "ACTIVE"


def test_ideas_are_mine_actions_and_cards_stay_in_needs_you(monkeypatch):
    client, db = _client(monkeypatch)
    _seed(db, suggestions=[
        {"id": "late", "user_id": "alice", "symbol": "TCS", "side": "BUY", "status": "PENDING", "mode": "LONGTERM",
         "quantity": 1, "expires_at": NOW + timedelta(days=3), "created_at": NOW},
        {"id": "soon", "user_id": "alice", "symbol": "SJVN", "side": "BUY", "status": "PENDING", "mode": "LONGTERM",
         "quantity": 1, "expires_at": NOW + timedelta(days=1), "created_at": NOW},
    ], chat_actions=[{"id": "c1", "user_id": "alice", "status": "PROPOSED", "summary": "Sell 10 INFY",
                      "expires_at": NOW + timedelta(minutes=10), "created_at": NOW}])
    body = client.get("/api/v1/today").json()
    items = body["needs_you"]
    assert {a["action"]["suggestion_id"] for a in body["mine_actions"] if a["kind"] == "idea"} == {"late", "soon"}
    assert not [n for n in items if n["kind"] == "proposal"]
    assert any(n["kind"] == "card" and "Sell 10 INFY" in n["title"] for n in items)


def test_needs_you_lists_long_term_proposals_only(monkeypatch):
    """Decisions shows long-term proposals only; Today must not count others."""
    client, db = _client(monkeypatch)
    _seed(db, suggestions=[
        {"id": "lt", "user_id": "alice", "symbol": "TCS", "side": "BUY", "status": "PENDING", "mode": "LONGTERM",
         "quantity": 1, "expires_at": NOW + timedelta(days=1), "created_at": NOW},
        {"id": "id", "user_id": "alice", "symbol": "SJVN", "side": "BUY", "status": "PENDING", "mode": "INTRADAY",
         "quantity": 1, "expires_at": NOW + timedelta(days=1), "created_at": NOW},
    ])
    ideas = [a["title"] for a in client.get("/api/v1/today").json()["mine_actions"] if a["kind"] == "idea"]
    assert len(ideas) == 1 and "TCS" in ideas[0]


def test_you_vs_picks_counts_only_the_ai_books_pick_trades(monkeypatch):
    client, db = _client(monkeypatch, role="admin")
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"kite": "ai", "upstox": "mine"}}],
          journal_trades=[
              {"_id": "t1", "user_id": "alice", "broker": "upstox", "exchange": "NSE", "symbol": "INFY",
               "side": "BUY", "quantity": 10, "price": 100.0, "traded_at": DAY + timedelta(minutes=1)},
              {"_id": "t2", "user_id": "alice", "broker": "upstox", "exchange": "NSE", "symbol": "INFY",
               "side": "SELL", "quantity": 10, "price": 110.0, "traded_at": DAY + timedelta(minutes=2)}],
          paper_trades=[{"user_id": "alice", "symbol": "TCS", "side": "BUY", "status": "CLOSED",
                         "strategy": "picks:momentum", "via": "autopilot:picks", "realized_pnl": -50.0, "costs": 5.0, "exit_at": DAY + timedelta(minutes=3), "venue": "paper"},
                        {"user_id": "alice", "symbol": "SBIN", "side": "BUY", "status": "CLOSED",  # not a pick
                         "strategy": "autopilot:chat", "via": "autopilot:chat", "realized_pnl": 900.0, "costs": 5.0, "exit_at": DAY + timedelta(minutes=3), "venue": "paper"}])
    pnl = client.get("/api/v1/today").json()["scoreboard"]["today"]
    # Both sides net of charges: the broker book carries none, so Mine's are estimated.
    assert pnl["ai"] == -55.0 and pnl["ai_charges"] == 5.0
    assert 0 < pnl["mine_charges"] < 5 and pnl["mine"] == round(100.0 - pnl["mine_charges"], 2)


def test_a_failing_part_degrades_not_errors(monkeypatch):
    client, db = _client(monkeypatch, broken=True)
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"kite": "ai"}}])
    resp = client.get("/api/v1/today")
    assert resp.status_code == 200
    assert resp.json()["accounts"] is None and "accounts" in resp.json()["errors"]


def test_autopilot_summary_counts_open_positions_against_capital(monkeypatch):
    client, db = _client(monkeypatch)
    _seed(db, user_prefs=[{"user_id": "alice", "autopilot_enabled": True, "max_exposure": 15000.0}],
          paper_trades=[{"user_id": "alice", "symbol": "INFY", "status": "OPEN", "quantity": 3,
                         "entry_price": 1500.0, "venue": "paper", "strategy": "autopilot:chat", "via": "autopilot:chat"},
                        {"user_id": "alice", "symbol": "TCS", "status": "OPEN", "quantity": 10,
                         "entry_price": 3000.0, "venue": "paper", "strategy": "macd_crossover"}])
    summary = client.get("/api/v1/today").json()["autopilot"]
    assert summary == {"enabled": True, "live": False, "capital": 15000.0, "deployed": 4500.0}


def test_you_vs_picks_is_admin_only(monkeypatch):
    client, _ = _client(monkeypatch)
    body = client.get("/api/v1/today").json()
    assert body["scoreboard"] is None and "scoreboard" not in body["errors"]


def test_selling_a_position_bought_before_today_counts_its_pnl(monkeypatch):
    client, db = _client(monkeypatch, role="admin")
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"upstox": "mine"}}], journal_trades=[
        {"_id": "y1", "user_id": "alice", "broker": "upstox", "exchange": "NSE", "symbol": "RELIANCE",
         "side": "BUY", "quantity": 10, "price": 90.0, "traded_at": DAY - timedelta(days=2)},
        {"_id": "t1", "user_id": "alice", "broker": "upstox", "exchange": "NSE", "symbol": "RELIANCE",
         "side": "SELL", "quantity": 10, "price": 100.0, "traded_at": DAY + timedelta(minutes=1)}])
    pnl = client.get("/api/v1/today").json()["scoreboard"]["today"]
    assert pnl["mine"] == round(100.0 - pnl["mine_charges"], 2) and pnl["mine_charges"] > 0


def test_activity_times_carry_their_timezone(monkeypatch):
    client, db = _client(monkeypatch)
    _seed(db, autopilot_log=[{"user_id": "alice", "at": datetime(2026, 10, 5, 4, 0), "status": "FILLED",
                              "side": "BUY", "symbol": "INFY", "quantity": 1}])
    at = client.get("/api/v1/today").json()["ai_activity"][0]["at"]
    assert at.endswith("+00:00") or at.endswith("Z")


def test_broker_states_are_cached_between_polls(monkeypatch):
    calls = []
    client, db = _client(monkeypatch)

    async def counting(user_id, brokers):
        calls.append(1)
        return {b: "ACTIVE" for b in brokers}

    client.app.dependency_overrides[today_router.get_broker_states] = lambda: counting
    monkeypatch.setattr(today_router, "_STATE_CACHE", {})
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"kite": "ai"}}])
    client.get("/api/v1/today")
    client.get("/api/v1/today")
    assert len(calls) == 1


def test_a_login_shows_on_the_next_poll(monkeypatch):
    """A logged-out session is cheap to re-check and is never reused: the poll
    after a broker login shows it live, on whichever worker answers."""
    states = {"upstox": "NEEDS_LOGIN"}
    client, db = _client(monkeypatch)

    async def current(user_id, brokers):
        return {b: states[b] for b in brokers}

    client.app.dependency_overrides[today_router.get_broker_states] = lambda: current
    monkeypatch.setattr(today_router, "_STATE_CACHE", {})
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"upstox": "mine"}}])
    assert client.get("/api/v1/today").json()["accounts"]["mine"]["state"] == "NEEDS_LOGIN"
    states["upstox"] = "ACTIVE"  # the user logs in
    assert client.get("/api/v1/today").json()["accounts"]["mine"]["state"] == "ACTIVE"


def test_proposals_carry_their_terms_and_the_full_count(monkeypatch):
    """Today shows the top few of Mine's list; an idea says how sure the engine
    is and which suggestion to approve, and the totals say how many wait."""
    client, db = _client(monkeypatch)
    _seed(db, suggestions=[
        {"id": f"p{i}", "user_id": "alice", "symbol": f"S{i}", "side": "BUY", "status": "PENDING", "mode": "LONGTERM",
         "quantity": 2, "entry_ref": 100.0, "notional": 200.0, "score": {"final": 0.61},
         "expires_at": NOW + timedelta(days=1), "created_at": NOW} for i in range(7)])
    body = client.get("/api/v1/today").json()
    ideas = body["mine_actions"]
    assert len(ideas) == 3 and body["mine_actions_total"] == 7 and body["proposals_total"] == 7
    assert ideas[0]["symbol"].startswith("S") and ideas[0]["title"] == f"BUY 2 {ideas[0]['symbol']}"
    assert ideas[0]["action"] == {"type": "idea", "suggestion_id": ideas[0]["id"].split(":")[2]}
    assert "conviction 0.61" in ideas[0]["detail"]


def test_attention_counts_what_needs_the_user_but_not_practice_proposals(monkeypatch):
    client, db = _client(monkeypatch, states={"upstox": "ACTIVE"})
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"kite": "ai", "upstox": "mine"}}],
          suggestions=[{"id": "p", "user_id": "alice", "symbol": "TCS", "side": "BUY", "status": "PENDING",
                        "mode": "LONGTERM", "quantity": 1, "expires_at": NOW + timedelta(days=1), "created_at": NOW}],
          chat_actions=[{"id": "c1", "user_id": "alice", "status": "PROPOSED", "summary": "Sell 10 INFY",
                         "expires_at": NOW + timedelta(minutes=10), "created_at": NOW}])
    assert client.get("/api/v1/today/attention").json() == {"count": 2}  # Kite login + the card


def test_a_broker_reconciliation_mismatch_is_a_do_today_item(monkeypatch):
    client, db = _client(monkeypatch)
    day = NOW.astimezone(IST).date().isoformat()
    _seed(db, broker_reconciliation=[
        {"_id": f"alice:{day}:ai", "user_id": "alice", "day": day, "role": "ai", "status": "mismatch",
         "checked_at": NOW, "mismatches": [{"kind": "unknown_order", "where": "ledger", "symbol": "ITC"}]},
        {"_id": f"alice:{day}:mine", "user_id": "alice", "day": day, "role": "mine", "status": "ok",
         "checked_at": NOW, "mismatches": []},
        {"_id": "bob:x:ai", "user_id": "bob", "day": day, "role": "ai", "status": "mismatch", "mismatches": []},
    ])
    items = [n for n in client.get("/api/v1/today").json()["needs_you"] if n["kind"] == "reconcile"]
    assert len(items) == 1 and items[0]["detail"] == "AI account: 1 (ITC)"
    rows = client.get("/api/v1/today/reconciliation").json()["results"]
    assert [(r["user_id"], r["role"]) for r in rows] == [("alice", "ai"), ("alice", "mine")]


def test_data_quality_alerts_show_only_to_the_admin(monkeypatch):
    from backend.system import data_quality

    async def alerts(db, redis, now):
        return ["Ingest loop quotes last beat 60 min ago"]
    monkeypatch.setattr(data_quality, "alerts", alerts)
    user, _ = _client(monkeypatch)
    assert not [n for n in user.get("/api/v1/today").json()["needs_you"] if n["kind"] == "data_quality"]
    admin, _ = _client(monkeypatch, role="admin")
    items = [n for n in admin.get("/api/v1/today").json()["needs_you"] if n["kind"] == "data_quality"]
    assert [(i["title"], i["link"]) for i in items] == [("Ingest loop quotes last beat 60 min ago", "/lab/handbook")]


def _at(monkeypatch, hour, minute=0, day=19):
    at = datetime(2026, 10, day, hour, minute, tzinfo=IST)
    monkeypatch.setattr(today_router, "_now", lambda: at.astimezone(timezone.utc))
    return at


def test_pre_market_has_the_premarket_text_only(monkeypatch):
    _at(monkeypatch, 8, 50)
    client, _ = _client(monkeypatch)
    body = client.get("/api/v1/today").json()
    assert body["phase"] == "pre" and body["postclose"] is None
    assert body["premarket"].startswith("\u2600\ufe0f <b>Before the open</b>")
    assert body["next_open"].startswith("2026-10-19T09:15")


def test_post_close_has_the_postclose_text_only(monkeypatch):
    _at(monkeypatch, 16, 0)
    client, _ = _client(monkeypatch)
    body = client.get("/api/v1/today").json()
    assert body["phase"] == "post" and body["premarket"] is None
    assert isinstance(body["postclose"], str) and "After the close" in body["postclose"]


def test_a_holiday_weekday_is_closed(monkeypatch):
    _at(monkeypatch, 10, day=20)
    client, _ = _client(monkeypatch)
    body = client.get("/api/v1/today").json()
    assert body["phase"] == "closed" and body["premarket"] is None and isinstance(body["postclose"], str)


def test_picks_top_is_admin_only_and_pre_only(monkeypatch):
    def pick(sym, edge):
        return {"_id": sym, "date": "2026-10-19", "symbol": sym, "label": sym + " setup", "median_excess": edge,
                "p_beat_nifty": 1.0, "strength": 1, "expected": {"median": edge}}
    rows = [pick("A", 1), pick("B", 4), pick("C", 3), pick("D", 2)]
    _at(monkeypatch, 8, 50)
    client, db = _client(monkeypatch, role="admin")
    _seed(db, picks=rows)
    assert [p["symbol"] for p in client.get("/api/v1/today").json()["picks_top"]] == ["B", "C", "D"]
    client, db = _client(monkeypatch)
    _seed(db, picks=rows)
    assert client.get("/api/v1/today").json()["picks_top"] is None
    _at(monkeypatch, 11)
    client, db = _client(monkeypatch, role="admin")
    _seed(db, picks=rows)
    assert client.get("/api/v1/today").json()["picks_top"] is None


def test_unjournaled_counts_todays_closed_trips_without_a_note(monkeypatch):
    at = _at(monkeypatch, 16, 0)

    def fill(sym, side, price, minute):
        return {"_id": f"{sym}-{side}", "user_id": "alice", "broker": "upstox", "exchange": "NSE", "symbol": sym,
                "side": side, "quantity": 1, "price": price, "traded_at": at.replace(hour=10, minute=minute)}
    client, db = _client(monkeypatch)
    trades = []
    for sym, minute in (("AAA", 1), ("BBB", 3), ("CCC", 5)):
        trades += [fill(sym, "BUY", 100.0, minute), fill(sym, "SELL", 101.0, minute + 1)]
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"upstox": "mine"}}], journal_trades=trades,
          journal_notes=[{"_id": "alice:AAA-BUY", "user_id": "alice", "round_trip_id": "AAA-BUY", "note": "ok", "tags": []}])
    assert client.get("/api/v1/today").json()["unjournaled"] == 2
