"""Guest browsing: the shared market/news/quote reads are open to signed-out
visitors; everything else on those routers still needs a user, and nothing a
guest can reach calls a model."""

from datetime import datetime, timezone

import pytest
from fastapi.routing import _iter_routes_with_context
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user, require_admin
from backend.database import db
from backend.server import app

PUBLIC = {
    ("GET", "/api/v1/market/indices"),
    ("GET", "/api/v1/market/trending"),
    ("GET", "/api/v1/market/global"),
    ("GET", "/api/v1/market/quotes"),
    ("GET", "/api/v1/market/scan"),
    ("GET", "/api/v1/market/brief"),
    ("GET", "/api/v1/market/index/{ticker}"),
    ("GET", "/api/v1/market/index/{ticker}/intraday"),
    ("GET", "/api/v1/market/index/{ticker}/analysis"),
    ("GET", "/api/v1/market/sector/{name}"),
    ("GET", "/api/v1/market/stock/{symbol}/events"),
    ("GET", "/api/v1/market/indices/more"),
    ("GET", "/api/v1/market/stock/{symbol}/indices"),
    ("GET", "/api/v1/market/index/{ticker}/stocks"),
    ("GET", "/api/v1/research/{symbol}/note"),
    ("GET", "/api/v1/news/feed"),
    ("GET", "/api/v1/news/item/{item_id}"),
    ("GET", "/api/v1/news/symbols"),
    ("GET", "/api/v1/news/symbol/{symbol}"),
    ("GET", "/api/v1/news/results"),
    ("GET", "/api/v1/agents/intraday/{symbol}"),
    ("POST", "/api/v1/agents/quick-analyze/{symbol}"),
    ("GET", "/api/v1/trading/instruments"),
}
OPENED = ("/api/v1/market", "/api/v1/research", "/api/v1/news", "/api/v1/agents")


def _needs(dependant) -> set:
    out = set()
    for dep in dependant.dependencies:
        out.add(dep.call)
        out |= _needs(dep)
    return out


def _routes():
    # FastAPI 0.162 keeps included routers lazy (app.routes holds _IncludedRouter
    # stubs); the effective contexts carry the full path and the mount-level deps.
    for _, ctx in _iter_routes_with_context(app.routes):
        if ctx is not None and ctx.dependant is not None and ctx.path.startswith("/api/v1"):
            for method in ctx.methods:
                yield (method, ctx.path), ctx


def test_public_routes_do_not_require_user():
    found = set()
    for key, route in _routes():
        if key in PUBLIC:
            found.add(key)
            needs = _needs(route.dependant)
            assert get_current_user not in needs, key
            assert require_admin not in needs, key
    assert found == PUBLIC


def test_every_other_route_on_opened_routers_requires_user():
    seen = set()
    for key, route in _routes():
        if key[1].startswith(OPENED) and key not in PUBLIC:
            seen.add(key)
            assert get_current_user in _needs(route.dependant), key
    assert {("GET", "/api/v1/news/accuracy"), ("POST", "/api/v1/agents/analyze/{symbol}")} <= seen


def test_guest_uncached_index_analysis_is_401(monkeypatch):
    from backend.research import index_move
    from backend.routers import market_data

    async def boom(*a, **k):
        raise AssertionError("guest reached the model")

    monkeypatch.setattr(market_data, "_known_index_names", lambda: {"^NSEI": "NIFTY 50"})
    monkeypatch.setattr(index_move, "explain_index_move", boom)
    resp = TestClient(app).get("/api/v1/market/index/^NSEI/analysis")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Sign in to generate an explanation"  # ours, not the bearer gate's


async def test_guest_news_feed_mine_ignores_mine(monkeypatch):
    from backend.datalayer.news import COLLECTION, SCORED
    from backend.routers.news import news_feed

    mongo = AsyncMongoMockClient()["test_db"]
    await mongo[COLLECTION].insert_one({"_id": "n1", "title": "T", "status": SCORED, "source": "x", "scope": "MARKET",
                                        "symbols": [], "impacts": [], "published_at": datetime.now(timezone.utc)})
    await mongo["paper_positions"].insert_one({"user_id": "someone", "symbol": "TCS", "quantity": 5})
    monkeypatch.setattr(db, "db", mongo)
    out = await news_feed(scope=None, mine=True, material=False, before=None, q=None, limit=50, user=None)
    assert [i["id"] for i in out["items"]] == ["n1"]


@pytest.mark.parametrize("headers, key", [
    ({"X-Forwarded-For": "9.9.9.9, 13.207.196.111", "X-Real-IP": "13.207.196.111"}, "quick_analyze:ip:9.9.9.9"),
    ({"X-Real-IP": "1.2.3.4"}, "quick_analyze:ip:1.2.3.4"),
])
def test_guest_quick_analyze_uses_ip_key(monkeypatch, headers, key):
    from backend import rate_limit
    from backend.research.quick import QuickAnalysis
    from backend.routers import agents

    calls = []

    async def allow(redis, key, limit, window):
        calls.append((key, limit, window))
        return True

    async def stub(symbol):
        return QuickAnalysis(symbol=symbol, company_info={}, price_data=[], technical_analysis={})

    monkeypatch.setattr(rate_limit, "allow", allow)
    monkeypatch.setattr(agents, "quick_analysis", stub)
    resp = TestClient(app).post("/api/v1/agents/quick-analyze/TCS", headers=headers)
    assert resp.status_code == 200
    assert calls == [(key, 30, 60)]
