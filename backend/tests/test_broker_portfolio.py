"""Portfolio phases 1-2: holdings from each broker (mocked with the
brokers' own documented/mock payloads), merged, and scored against NIFTY
lot by lot from the journal's buy dates."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.brokers.holdings import kind_of
from backend.brokers.kite_orders import KiteOrderClient
from backend.core.models import Holding
from backend.portfolio import service
from backend.portfolio.scorecard import build_scorecard, correlated_pairs, merge, open_lots
from backend.tests.test_angel_one_adapter import _adapter as _angel
from backend.tests.test_angel_one_adapter import _redis as _angel_redis
from backend.tests.test_upstox_adapter import _adapter as _upstox
from backend.tests.test_upstox_adapter import _redis as _upstox_redis


def test_etfs_are_told_apart_by_name():
    assert [kind_of(s) for s in ("NIFTYBEES", "GOLDBEES-EQ", "MON100", "SETFNIF50", "RELIANCE")] == [
        "ETF", "ETF", "STOCK", "ETF", "STOCK",
    ]


async def test_kite_holdings_include_t1_shares_and_mutual_funds():
    kite = MagicMock()
    kite.holdings.return_value = [
        {"tradingsymbol": "AARON", "exchange": "NSE", "isin": "INE721Z01010", "quantity": 1, "t1_quantity": 2,
         "average_price": 161, "last_price": 352.95, "close_price": 352.35},
        {"tradingsymbol": "SOLD", "exchange": "NSE", "isin": "X", "quantity": 0, "t1_quantity": 0,
         "average_price": 1, "last_price": 1, "close_price": 1},
    ]
    kite.mf_holdings.return_value = [
        {"folio": "1", "fund": "INVESCO INDIA TAX PLAN - DIRECT PLAN", "tradingsymbol": "INF205K01NT8",
         "average_price": 78.43, "last_price": 84.86, "quantity": 382.488},
    ]
    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())):
        stock, fund = await KiteOrderClient(lambda: kite).get_holdings()
    assert (stock.symbol, stock.quantity, stock.avg_price, stock.kind) == ("AARON", 3.0, 161.0, "STOCK")
    assert (fund.kind, fund.isin, fund.name, fund.quantity) == (
        "MF", "INF205K01NT8", "INVESCO INDIA TAX PLAN - DIRECT PLAN", 382.488,
    )


async def test_upstox_holdings(monkeypatch):
    redis = _upstox_redis()
    await redis.set("broker:alice:upstox:access_token", "up-tok")

    async def fake_get(self, url, **kwargs):
        assert url == "https://api.upstox.com/v2/portfolio/long-term-holdings"
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [
            {"isin": "INE002A01018", "company_name": "RELIANCE INDUSTRIES", "trading_symbol": "RELIANCE",
             "exchange": "NSE", "quantity": 10, "average_price": 2400.0, "last_price": 2900.0, "close_price": 2880.0},
        ]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    (holding,) = await _upstox(redis).get_holdings()
    assert (holding.symbol, holding.name, holding.quantity, holding.broker) == (
        "RELIANCE", "RELIANCE INDUSTRIES", 10.0, "upstox",
    )


async def test_angel_one_holdings_strip_the_eq_suffix(monkeypatch):
    redis = _angel_redis()
    await redis.set("broker:alice:angel_one:access_token", "jwt")

    async def fake_get(self, url, **kwargs):
        assert url.endswith("/rest/secure/angelbroking/portfolio/v1/getHolding")
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [
            {"tradingsymbol": "TCS-EQ", "exchange": "NSE", "isin": "INE467B01029", "quantity": "4",
             "t1quantity": "1", "averageprice": 3500.0, "ltp": 3900.0, "close": 3880.0},
        ]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    (holding,) = await _angel(redis).get_holdings()
    assert (holding.symbol, holding.quantity, holding.last_price) == ("TCS", 5.0, 3900.0)


def _h(symbol, quantity, avg, last, broker="kite", isin=None, kind="STOCK", close=None):
    return Holding(symbol=symbol, isin=isin or symbol, quantity=quantity, avg_price=avg, last_price=last,
                   close_price=close, broker=broker, kind=kind)


def test_merge_joins_the_same_isin_across_brokers():
    (row,) = merge([_h("RELIANCE", 10, 2000, 2900), _h("RELIANCE", 10, 3000, 2900, broker="upstox")])
    assert row["quantity"] == 20 and row["avg_price"] == 2500 and row["brokers"] == ["kite", "upstox"]


def _t(symbol, side, quantity, price, day):
    return {"symbol": symbol, "side": side, "quantity": quantity, "price": price,
            "traded_at": datetime(2024, 1, day, 6, 0, tzinfo=timezone.utc)}


def test_open_lots_use_up_the_oldest_buys_first():
    trades = [_t("A", "BUY", 10, 100, 1), _t("A", "BUY", 10, 120, 5), _t("A", "SELL", 15, 130, 8)]
    assert open_lots(trades, "A") == [(date(2024, 1, 5), 5.0, 120.0)]


def test_scorecard_totals_weights_and_nifty_comparison():
    holdings = [
        _h("A", 10, 100, 150, close=140),   # journal knows it: bought 2 Jan
        _h("B", 10, 100, 50),               # bought before the journal began
        _h("NIFTYBEES", 100, 20, 25, kind="ETF"),
    ]
    trades = [_t("A", "BUY", 10, 100, 2)]
    nifty = [(date(2024, 1, 1), 20000.0), (date(2024, 1, 2), 20000.0), (date(2024, 6, 1), 22000.0)]
    card = build_scorecard(holdings, trades, nifty, {"A": "Energy", "B": None}, {})

    totals = card["totals"]
    assert (totals["invested"], totals["value"], totals["pnl"]) == (4000, 4500, 500)
    assert totals["day_change"] == 100  # only A has a close to compare with
    a = next(r for r in card["holdings"] if r["symbol"] == "A")
    assert a["first_bought"] == "2024-01-02" and a["nifty_pnl_pct"] == pytest.approx(10.0)
    bench = card["benchmark"]
    assert bench["covered_pct"] == pytest.approx(25.0)  # 1000 of 4000 invested
    assert (bench["portfolio_pct"], bench["nifty_pct"]) == (pytest.approx(50.0), pytest.approx(10.0))
    sectors = {s["sector"]: round(s["pct"], 1) for s in card["concentration"]["sectors"]}
    assert sectors == {"Energy": 33.3, "Unclassified": 11.1, "Funds & ETFs": 55.6}
    assert card["concentration"]["top_symbol"] == "NIFTYBEES"
    assert 2.0 < card["concentration"]["effective_holdings"] < 3.0


def test_correlated_pairs_need_overlap_and_strength():
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(80)]
    wave = [((i * 7) % 11 - 5) / 100 for i in range(80)]
    returns = {
        "HDFCBANK": dict(zip(days, wave)),
        "ICICIBANK": dict(zip(days, [w * 1.1 + 0.001 for w in wave])),
        "ITC": dict(zip(days, [((i * 3) % 7 - 3) / 100 for i in range(80)])),
        "NEW": dict(zip(days[:20], wave[:20])),
    }
    (pair,) = correlated_pairs(returns)
    assert (pair["a"], pair["b"]) == ("HDFCBANK", "ICICIBANK") and pair["correlation"] == 1.0


async def test_refresh_saves_a_snapshot_and_reports_a_failed_broker(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]

    class _Broker:
        def __init__(self, holdings=None, fail=False):
            self.holdings, self.fail = holdings or [], fail

        async def state(self):
            from backend.brokers.protocol import BrokerSessionState
            return BrokerSessionState.ACTIVE

        async def get_holdings(self):
            if self.fail:
                raise RuntimeError("token expired")
            return self.holdings

    brokers = {"kite": _Broker([_h("A", 10, 100, 150)]), "upstox": _Broker(fail=True), "angel_one": _Broker()}
    monkeypatch.setattr(service, "get_broker_adapter", AsyncMock(side_effect=lambda b, *a: brokers[b]))
    monkeypatch.setattr(service, "_nifty", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "_sector_sync", lambda ticker: "Energy")
    monkeypatch.setattr(service, "_daily_returns_sync", lambda tickers: {})

    snapshot = await service.refresh_portfolio(db, "alice", None, None)
    assert snapshot["errors"] == {"upstox": "token expired"} and snapshot["brokers"] == ["kite"]
    assert snapshot["totals"]["value"] == 1500
    latest = await service.latest_snapshot(db, "alice")
    assert latest["holdings"][0]["sector"] == "Energy" and latest["user_id"] == "alice"
    assert await service.latest_snapshot(db, "bob") is None
    assert (await db["instrument_sectors"].find_one({"_id": "A"}))["sector"] == "Energy"
