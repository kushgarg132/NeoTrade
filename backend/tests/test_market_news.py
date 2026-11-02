"""Statement headlines: today's Indian market news, newest first, each story
once, nothing older than a day and a half."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import market_cache
from backend.routers import news
from backend.core.models import NewsArticle


def _article(title, hours_ago):
    return NewsArticle(title=title, url=f"https://x/{hours_ago}/{title}", source="Wire",
                       published_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours_ago))


@pytest.fixture
def searches(monkeypatch):
    calls = []

    async def fake(query, region="US", lang="en-US", limit=10):
        calls.append((query, region, lang))
        return [
            _article("Sensex ends 400 points lower as banks drag - Mint", 2),
            _article("Sensex ends 400 points lower as banks drag - The Economic Times", 3),
            _article("Rupee hits record low against dollar - Reuters", 1),
            _article("Midwest Energy Limited (REMAGNET.BO) stock price", 24 * 60),
        ]

    monkeypatch.setattr(news, "fetch_google_news", fake)
    monkeypatch.setattr(market_cache, "_local", {})
    return calls


@pytest.mark.asyncio
async def test_fresh_headlines_are_newest_first_deduped_and_recent(searches):
    articles = await news.fresh_headlines(news.MARKET_QUERIES)
    assert [a.title for a in articles] == [
        "Rupee hits record low against dollar - Reuters",
        "Sensex ends 400 points lower as banks drag - Mint",
    ]
    assert all(region == "IN" and "when:1d" in q for q, region, _ in searches)


def test_news_feed_filters_to_the_users_names(monkeypatch):
    import asyncio
    from mongomock_motor import AsyncMongoMockClient
    from backend.auth.dependency import get_optional_user
    from backend.auth.models import User
    from backend.database import db as database

    mongo = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(database, "db", mongo)
    now = datetime.now(timezone.utc)

    def item(_id, minutes, **extra):
        return {"_id": _id, "title": _id, "status": "SCORED", "scope": "COMPANY", "symbols": [], "impacts": [],
                "published_at": now - timedelta(minutes=minutes), **extra}

    asyncio.run(mongo["news_items"].insert_many([
        item("tcs", 1, symbols=["TCS"]), item("infy", 2, impacts=[{"type": "symbol", "target": "INFY"}]),
        item("rbi", 3, scope="MACRO"), item("junk", 4, status="IRRELEVANT"),
        item("record-date", 5, source="NSE filing", symbols=["WIPRO"]),
        item("order-win", 6, source="NSE filing", symbols=["HDFCBANK"], impacts=[{"type": "symbol", "target": "HDFCBANK"}]),
    ]))
    asyncio.run(mongo["portfolio_snapshots"].insert_one(
        {"user_id": "alice", "at": now, "holdings": [{"symbol": "HDFCBANK"}, {"symbol": "WIPRO"}]}))
    asyncio.run(mongo["paper_positions"].insert_one({"user_id": "alice", "symbol": "TCS.NS", "quantity": 1}))
    asyncio.run(mongo["watchlist"].insert_one({"user_id": "alice", "symbols": ["INFY"]}))

    app = FastAPI()
    app.include_router(news.router)
    app.dependency_overrides[get_optional_user] = lambda: User(id="alice", google_sub="g", email="a@x.io", name="A",
                                                             created_at=now)
    client = TestClient(app)
    ids = lambda **params: [i["id"] for i in client.get("/news/feed", params=params).json()["items"]]
    # A filing the scorer found moves nothing is left out; one that moves a name stays.
    assert ids() == ["tcs", "infy", "rbi", "order-win"]
    # Mine: paper positions, the watchlist and the broker holdings.
    assert ids(mine=True) == ["tcs", "infy", "order-win"]
    assert ids(scope="MACRO") == ["rbi"]
    assert ids(limit=1) == ["tcs"]

    # Search: headline text (case-insensitive, regex characters taken literally) or a symbol it tags or moves.
    asyncio.run(mongo["news_items"].insert_one(item("Q2 (beat) & guidance up", 7, symbols=["LT"])))
    assert ids(q="ORDER") == ["order-win"]
    assert ids(q="infy") == ["infy"]
    assert ids(q="tcs") == ["tcs"]
    assert ids(q="(beat) &") == ["Q2 (beat) & guidance up"]
    assert ids(q=".*") == []
    assert ids(q="  ") == ["tcs", "infy", "rbi", "order-win", "Q2 (beat) & guidance up"]
    # Combined with mine (its own $or) and scope.
    assert ids(q="hdfcbank", mine=True) == ["order-win"]
    assert ids(q="tcs", scope="MACRO") == []
    assert client.get("/news/feed", params={"q": "x" * 81}).status_code == 422


def _symbols_client(monkeypatch, items, sentiments):
    import asyncio

    from mongomock_motor import AsyncMongoMockClient

    from backend.auth.dependency import get_optional_user
    from backend.auth.models import User
    from backend.database import db as database
    from backend.tests.test_datalayer_news import FakeRedis

    mongo, redis = AsyncMongoMockClient()["test_db"], FakeRedis()
    monkeypatch.setattr(database, "db", mongo)
    monkeypatch.setattr(database, "redis", redis)
    for symbol, value in sentiments.items():
        redis.data[f"sentiment:{symbol}"] = str(value)
    if items:
        asyncio.run(mongo["news_items"].insert_many(items))
    app = FastAPI()
    app.include_router(news.router)
    app.dependency_overrides[get_optional_user] = lambda: User(id="alice", google_sub="g", email="a@x.io", name="A",
                                                             created_at=datetime.now(timezone.utc))
    return TestClient(app)


def test_symbol_news_summarises_sentiment_and_latest_headline(monkeypatch):
    now = datetime.now(timezone.utc)

    def item(_id, hours, target, impact, direction, material=False):
        return {"_id": _id, "title": f"title {_id}", "url": f"https://x/{_id}", "status": "SCORED",
                "material": material, "published_at": now - timedelta(hours=hours),
                "impacts": [{"type": "symbol", "target": target, "impact": impact, "direction": direction}]}
    client = _symbols_client(monkeypatch, [item("old", 5, "TCS", 9, 0.8), item("new", 1, "TCS", 7, -0.6, True),
                                           item("stale", 100, "INFY", 9, 0.9)], {"TCS": -0.3, "WIPRO": 0.1})
    body = client.get("/news/symbols", params={"symbols": "tcs.NS,INFY,WIPRO"}).json()["symbols"]
    assert body["TCS"]["headline"] == "title new" and body["TCS"]["direction"] == -0.6
    assert body["TCS"]["material"] is True and body["TCS"]["sentiment"] == -0.3
    assert body["TCS"]["id"] and body["TCS"]["impacts"][0]["target"] == "TCS"  # the News tab's analysis
    assert body["WIPRO"] == {"sentiment": 0.1, "headline": None, "direction": None, "impact": None,
                             "material": False, "published_at": None, "url": None, "id": None, "impacts": []}
    assert "INFY" not in body  # its only news is older than 72h and it has no sentiment


def test_symbol_news_omits_quiet_names_and_caps_the_list(monkeypatch):
    client = _symbols_client(monkeypatch, [], {})
    many = ",".join(f"S{i}" for i in range(150))
    response = client.get("/news/symbols", params={"symbols": many})
    assert response.status_code == 200 and response.json() == {"symbols": {}}
    assert client.get("/news/symbols", params={"symbols": ""}).json() == {"symbols": {}}


def test_symbol_news_prefers_material_bad_news_and_judges_materiality_per_symbol(monkeypatch):
    now = datetime.now(timezone.utc)

    def item(_id, hours, impacts, material=True):
        return {"_id": _id, "title": f"title {_id}", "url": None, "status": "SCORED", "material": material,
                "published_at": now - timedelta(hours=hours), "impacts": impacts}
    client = _symbols_client(monkeypatch, [
        item("big", 5, [{"type": "symbol", "target": "TCS", "impact": 8, "direction": -0.8}]),
        item("small", 1, [{"type": "symbol", "target": "TCS", "impact": 2, "direction": 0.1}], material=False),
        # material for the sector, only 2/10 for INFY itself
        item("sector", 1, [{"type": "sector", "target": "IT", "impact": 9, "direction": -0.9},
                           {"type": "symbol", "target": "INFY", "impact": 2, "direction": -0.2}]),
    ], {})
    body = client.get("/news/symbols", params={"symbols": "TCS,INFY"}).json()["symbols"]
    assert body["TCS"]["headline"] == "title big" and body["TCS"]["material"] is True
    assert body["INFY"]["material"] is False


def test_symbol_news_reads_sentiment_in_one_round_trip(monkeypatch):
    client = _symbols_client(monkeypatch, [], {"TCS": 0.3, "INFY": -0.2})
    from backend.database import db as database

    gets = []
    original = database.redis.get

    async def counting_get(key):
        gets.append(key)
        return await original(key)
    database.redis.get = counting_get
    body = client.get("/news/symbols", params={"symbols": "TCS,INFY"}).json()["symbols"]
    assert body["TCS"]["sentiment"] == 0.3 and body["INFY"]["sentiment"] == -0.2 and gets == []


def test_symbol_history_returns_scored_items_with_this_symbols_impact(monkeypatch):
    now = datetime.now(timezone.utc)

    def item(_id, days, impacts, symbols=(), status="SCORED"):
        return {"_id": _id, "title": f"title {_id}", "url": f"https://x/{_id}", "status": status,
                "published_at": now - timedelta(days=days), "impacts": impacts, "symbols": list(symbols)}
    client = _symbols_client(monkeypatch, [
        item("big", 2, [{"type": "sector", "target": "IT", "impact": 9, "direction": 0.9},
                        {"type": "symbol", "target": "TCS", "impact": 8, "direction": -0.7}]),
        item("tagged", 1, [], symbols=["TCS"]),
        item("other", 1, [{"type": "symbol", "target": "INFY", "impact": 9, "direction": 0.5}]),
        item("unscored", 1, [], symbols=["TCS"], status="TRIAGED"),
        item("old", 40, [{"type": "symbol", "target": "TCS", "impact": 9, "direction": 0.5}]),
    ], {})
    body = client.get("/news/symbol/tcs.NS", params={"days": 30}).json()
    assert body["symbol"] == "TCS" and [i["id"] for i in body["items"]] == ["tagged", "big"]
    tagged, big = body["items"]
    assert big["direction"] == -0.7 and big["impact"] == 8 and big["material"] is True
    assert tagged["direction"] is None and tagged["material"] is False
    assert client.get("/news/symbol/TCS", params={"days": 400}).status_code == 422


def test_symbol_results_gives_the_next_results_date(monkeypatch):
    import asyncio

    from backend.database import db as database
    from backend.datalayer.bars import today_ist

    client = _symbols_client(monkeypatch, [], {})
    today = today_ist()

    def day(n):
        return (today + timedelta(days=n)).isoformat()
    asyncio.run(database.db["corporate_events"].insert_many([
        {"symbol": "TCS", "kind": "results", "date": day(30), "amount": None},
        {"symbol": "TCS", "kind": "results", "date": day(10), "amount": None},
        {"symbol": "TCS", "kind": "results", "date": day(-5), "amount": None},
        {"symbol": "INFY", "kind": "ex_dividend", "date": day(3), "amount": 5.0},
        {"symbol": "WIPRO", "kind": "results", "date": day(400), "amount": None},
    ]))
    assert client.get("/news/results", params={"symbols": "tcs.NS,INFY,WIPRO"}).json() == {"results": {"TCS": day(10)}}
    assert client.get("/news/results").json() == {"results": {}}


def _stock_client(monkeypatch, known=("KPITTECH",)):
    import asyncio

    from mongomock_motor import AsyncMongoMockClient

    from backend.auth.dependency import get_optional_user
    from backend.database import db as database
    from backend.routers import market_data

    mongo = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(database, "db", mongo)
    monkeypatch.setattr(database, "redis", None)
    market_cache._local.clear()
    for symbol in known:
        asyncio.run(mongo["instruments"].insert_one({"exchange": "NSE", "tradingsymbol": symbol}))
    app = FastAPI()
    app.include_router(news.router)
    app.include_router(market_data.router)
    app.dependency_overrides[get_optional_user] = lambda: None
    return TestClient(app), mongo


def test_live_headlines_only_when_asked_nothing_stored_and_the_name_is_real(monkeypatch):
    client, mongo = _stock_client(monkeypatch)
    calls = []

    async def fake(symbols, limit=10):
        calls.append(symbols)
        return [_article("KPIT wins a deal", 2), _article("KPIT last quarter", 24 * 40)]
    monkeypatch.setattr(news, "fetch_news_logic", fake)

    assert client.get("/news/symbol/KPITTECH?days=30").json()["items"] == []  # the chart's markers
    assert calls == []
    items = client.get("/news/symbol/KPITTECH.NS?days=30&live=true").json()["items"]
    assert [i["title"] for i in items] == ["KPIT wins a deal"]  # older than `days` is dropped
    assert items[0]["id"] is None and items[0]["impact"] is None and items[0]["published_at"].endswith("+00:00")
    client.get("/news/symbol/KPITTECH?days=30&live=true")
    assert calls == [["KPITTECH"]]  # cached

    assert client.get("/news/symbol/NOTREAL?days=30&live=true").json()["items"] == []
    assert calls == [["KPITTECH"]]  # an unknown symbol never reaches Google


def test_stored_news_wins_over_live_headlines(monkeypatch):
    import asyncio

    client, mongo = _stock_client(monkeypatch)

    async def boom(symbols, limit=10):
        raise AssertionError("no live fetch when news is stored")
    monkeypatch.setattr(news, "fetch_news_logic", boom)
    asyncio.run(mongo["news_items"].insert_one({
        "_id": "a", "status": "SCORED", "title": "Stored", "symbols": ["KPITTECH"], "impacts": [],
        "published_at": datetime.now(timezone.utc) - timedelta(hours=1)}))
    assert [i["title"] for i in client.get("/news/symbol/KPITTECH?days=30&live=true").json()["items"]] == ["Stored"]


def test_stock_events_fetch_real_names_once_and_are_public(monkeypatch):
    from backend.datalayer import results
    from backend.mine import events

    client, _ = _stock_client(monkeypatch)
    today = datetime.now(timezone.utc) + timedelta(hours=6)
    soon = (today + timedelta(days=9)).date().isoformat()
    calls = []

    def fetch(tkr):
        calls.append(tkr)
        return [{"kind": "results", "date": soon, "amount": None},
                {"kind": "ex_dividend", "date": "2026-01-05", "amount": 3.5}]
    monkeypatch.setattr(events, "_fetch_sync", fetch)
    monkeypatch.setattr(results, "_fetch_sync", lambda tkr, limit: [datetime(2026, 8, 1, 15, 0)])
    monkeypatch.setattr(results, "PAUSE", 0)

    body = client.get("/market/stock/KPITTECH.NS/events").json()
    assert [(e["kind"], e["date"]) for e in body["events"]] == [("results", soon)]
    assert body["past_events"] == {"dividends": [{"date": "2026-01-05", "per_share": 3.5}], "results": ["2026-08-01"]}
    client.get("/market/stock/KPITTECH/events")
    assert len(calls) == 1  # once a day

    assert client.get("/market/stock/NOTREAL/events").json() == {"events": [], "past_events": {"dividends": [], "results": []}}
    assert len(calls) == 1  # an unknown symbol never reaches Yahoo


def test_stock_events_answer_with_what_is_stored_when_the_fetch_hangs(monkeypatch):
    import asyncio

    from backend.datalayer import results
    from backend.mine import events
    from backend.routers import market_data

    client, _ = _stock_client(monkeypatch)
    monkeypatch.setattr(market_data, "EVENTS_FETCH_WAIT", 0.01)

    async def slow(*args, **kwargs):
        await asyncio.sleep(5)
    monkeypatch.setattr(events, "refresh", slow)
    monkeypatch.setattr(results, "refresh", slow)
    assert client.get("/market/stock/KPITTECH/events").json()["events"] == []


def test_every_extra_index_is_known_and_every_member_list_loads():
    from backend.datalayer import index_members
    from backend.routers import market_data

    known = market_data._known_index_names()
    for ticker in [*market_data.BROAD_INDICES.values(), *market_data.SECTOR_INDICES.values()]:
        assert ticker in known
        assert index_members.members(ticker), ticker
    for ticker in index_members.FILES:
        assert ticker in known and len(index_members.members(ticker)) >= 10, ticker
    assert "RELIANCE" in {r["symbol"] for r in index_members.members("^NSEI")}
    assert len(index_members.members("^NSEI")) == 50
    assert index_members.members("^BSESN") == () and index_members.members("^GSPC") == ()


def test_index_stocks_merge_cached_and_fetched_quotes(monkeypatch):
    from backend.routers import market_data

    client, _ = _stock_client(monkeypatch)
    monkeypatch.setattr(market_data.index_members, "members", lambda t: (
        {"symbol": "AAA", "name": "A Ltd", "sector": "IT"}, {"symbol": "BBB", "name": "B Ltd", "sector": "IT"},
        {"symbol": "CCC", "name": "C Ltd", "sector": "IT"}) if t == "^CNXIT" else ())

    async def cached_quotes(symbols):
        return {"AAA": {"symbol": "AAA", "price": 10.0, "change_pct": 1.5, "at": 111}}
    asked = []

    def fetched(symbols):
        asked.append(symbols)
        return [{"symbol": "BBB", "price": 20.0, "change_pct": -2.0, "at": 222}]
    monkeypatch.setattr(market_data, "_cached_quotes", cached_quotes)
    monkeypatch.setattr(market_data, "_quotes_sync", fetched)

    stocks = client.get("/market/index/^CNXIT/stocks").json()["stocks"]
    assert asked == [["BBB", "CCC"]]
    assert [(s["symbol"], s["price"], s["change_pct"]) for s in stocks] == [("AAA", 10.0, 1.5), ("BBB", 20.0, -2.0), ("CCC", None, None)]
    assert stocks[0]["name"] == "A Ltd"
    assert client.get("/market/index/^BSESN/stocks").status_code == 404


def test_index_stocks_list_names_even_with_no_quotes(monkeypatch):
    from backend.routers import market_data

    client, _ = _stock_client(monkeypatch)

    async def none(symbols):
        return {}

    def down(symbols):
        raise RuntimeError("Yahoo down")
    monkeypatch.setattr(market_data, "_cached_quotes", none)
    monkeypatch.setattr(market_data, "_quotes_sync", down)
    stocks = client.get("/market/index/^CNXIT/stocks").json()["stocks"]
    assert len(stocks) >= 10 and stocks[0]["price"] is None
    assert "index_stocks:^CNXIT" not in market_cache._local  # an outage is not cached


def test_more_indices_split_by_group(monkeypatch):
    from backend.routers import market_data

    client, _ = _stock_client(monkeypatch)

    async def quotes(names):
        return [{"name": n, "symbol": s, "value": 1, "percent": 0.5} for n, s in names.items()]
    monkeypatch.setattr(market_data, "_quotes", quotes)
    body = client.get("/market/indices/more").json()
    assert [r["symbol"] for r in body["broad"]] == list(market_data.BROAD_INDICES.values())
    assert [r["symbol"] for r in body["sectors"]] == list(market_data.SECTOR_INDICES.values())
