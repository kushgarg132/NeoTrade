"""Trade journal: broker trade books normalized, grouped into round trips,
stored idempotently, and Console CSV history imported."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.brokers.angel_one import AngelOneAdapter
from backend.brokers.kite_orders import KiteOrderClient
from backend.brokers.trades import parse_ist
from backend.brokers.upstox import UpstoxAdapter
from backend.core.models import BrokerTrade, Side
from backend.journal.console_csv import parse_console_tradebook
from backend.journal.roundtrips import build_round_trips, daily_pnl
from backend.journal.store import JournalStore


def _utc(h, m=0, day=1):
    """IST h:m on 2026-09-<day>, as UTC."""
    return parse_ist(datetime(2026, 9, day, h, m))


def _t(tid, side, qty, price, when, symbol="RELIANCE"):
    return {"_id": f"u:kite:{tid}", "broker": "kite", "exchange": "NSE", "symbol": symbol,
            "side": side, "quantity": qty, "price": price, "traded_at": when}


def _redis(token="tok"):
    redis = MagicMock()
    redis.get = AsyncMock(return_value=token)
    return redis


# -- timestamps -------------------------------------------------------------

def test_parse_ist_formats_all_land_on_the_same_utc_instant():
    expected = datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
    assert parse_ist("2026-09-01 09:30:00") == expected
    assert parse_ist("01-Sep-2026 09:30:00") == expected
    assert parse_ist("2026-09-01T09:30:00") == expected
    assert parse_ist(datetime(2026, 9, 1, 9, 30)) == expected
    assert parse_ist("09:30:00", on_day=datetime(2026, 9, 1).date()) == expected
    with pytest.raises(ValueError):
        parse_ist("yesterday")


# -- round trips ------------------------------------------------------------

def test_long_round_trip_with_scaled_exit():
    trips = build_round_trips([
        _t(1, "BUY", 10, 100.0, _utc(9, 20)),
        _t(2, "SELL", 4, 110.0, _utc(10)),
        _t(3, "SELL", 6, 105.0, _utc(11)),
    ])
    assert len(trips) == 1
    trip = trips[0]
    assert trip["direction"] == "LONG"
    assert trip["quantity"] == 10
    assert trip["pnl"] == 4 * 10 + 6 * 5  # 70
    assert trip["exit_price"] == pytest.approx(107.0)
    assert trip["day"] == "2026-09-01"
    assert trip["trade_ids"] == ["u:kite:1", "u:kite:2", "u:kite:3"]


def test_short_round_trip_profits_when_price_falls():
    trips = build_round_trips([_t(1, "SELL", 5, 200.0, _utc(9, 20)), _t(2, "BUY", 5, 190.0, _utc(9, 40))])
    assert trips[0]["direction"] == "SHORT"
    assert trips[0]["pnl"] == 50.0


def test_fill_crossing_zero_closes_one_trip_and_opens_the_opposite():
    trips = build_round_trips([
        _t(1, "BUY", 10, 100.0, _utc(9, 20)),
        _t(2, "SELL", 15, 90.0, _utc(10)),
        _t(3, "BUY", 5, 80.0, _utc(11)),
    ])
    assert [(t["direction"], t["pnl"]) for t in trips] == [("LONG", -100.0), ("SHORT", 50.0)]


def test_unclosed_position_is_an_open_trip_without_pnl():
    trips = build_round_trips([_t(1, "BUY", 10, 100.0, _utc(9, 20)), _t(2, "SELL", 3, 101.0, _utc(10))])
    assert trips[0]["closed_at"] is None
    assert trips[0]["pnl"] is None
    assert daily_pnl(trips) == []


def test_symbols_are_matched_independently_and_calendar_groups_by_ist_day():
    trips = build_round_trips([
        _t(1, "BUY", 1, 100.0, _utc(9, 20), "TCS"),
        _t(2, "BUY", 1, 50.0, _utc(9, 21), "INFY"),
        _t(3, "SELL", 1, 90.0, _utc(10), "TCS"),
        _t(4, "SELL", 1, 60.0, _utc(10), "INFY"),
        _t(5, "BUY", 1, 100.0, _utc(9, 20, day=2), "TCS"),
        _t(6, "SELL", 1, 130.0, _utc(15, 20, day=2), "TCS"),
    ])
    assert daily_pnl(trips) == [
        {"day": "2026-09-01", "pnl": 0.0, "trips": 2, "wins": 1},
        {"day": "2026-09-02", "pnl": 30.0, "trips": 1, "wins": 1},
    ]


# -- store ------------------------------------------------------------------

def _bt(tid, side=Side.BUY):
    return BrokerTrade(trade_id=tid, symbol="RELIANCE", side=side, quantity=1, price=100.0,
                       traded_at=_utc(9, 30))


async def test_store_is_idempotent_and_scoped_per_user():
    store = JournalStore(AsyncMongoMockClient()["test_db"])
    assert await store.add_trades("alice", "kite", [_bt("1"), _bt("2", Side.SELL)], source="sync") == 2
    assert await store.add_trades("alice", "kite", [_bt("1"), _bt("3")], source="sync") == 1
    assert await store.add_trades("bob", "kite", [_bt("1")], source="sync") == 1

    alice = await store.list_trades("alice")
    assert len(alice) == 3
    assert {t["side"] for t in alice} == {"BUY", "SELL"}
    assert alice[0]["traded_at"].tzinfo is not None
    assert build_round_trips(alice)[0]["pnl"] == 0.0


async def test_notes_are_per_user():
    store = JournalStore(AsyncMongoMockClient()["test_db"])
    await store.set_note("alice", "alice:kite:1", "chased the open", ["fomo"])
    assert await store.notes_for("alice") == {"alice:kite:1": {"note": "chased the open", "tags": ["fomo"]}}
    assert await store.notes_for("bob") == {}


# -- Console CSV ------------------------------------------------------------

_CSV = """symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
RELIANCE,INE002A01018,2024-04-01,NSE,EQ,EQ,buy,false,10.000000,2950.500000,55001,1100000001,2024-04-01T09:15:23
RELIANCE,INE002A01018,2024-04-01,NSE,EQ,EQ,sell,false,10.000000,2960.000000,55002,1100000002,2024-04-01T14:02:10
BROKEN,,2024-04-01,NSE,EQ,EQ,hold,false,x,1,55003,1,2024-04-01T14:02:10
"""


def test_console_csv_parses_rows_and_skips_bad_ones():
    trades, skipped = parse_console_tradebook("﻿" + _CSV)
    assert skipped == 1
    assert [(t.trade_id, t.side, t.quantity) for t in trades] == [("55001", Side.BUY, 10), ("55002", Side.SELL, 10)]
    assert trades[0].traded_at == datetime(2024, 4, 1, 3, 45, 23, tzinfo=timezone.utc)


def test_console_csv_rejects_a_different_file():
    with pytest.raises(ValueError, match="missing columns"):
        parse_console_tradebook("date,amount\n2024-01-01,5\n")


# -- adapters ---------------------------------------------------------------

async def test_kite_get_trades_maps_the_sdk_rows():
    kite = MagicMock()
    kite.trades.return_value = [{
        "trade_id": "10000000", "order_id": "200000", "exchange": "NSE", "tradingsymbol": "SBIN",
        "transaction_type": "SELL", "quantity": 5, "average_price": 800.5,
        "fill_timestamp": datetime(2026, 9, 1, 10, 0), "exchange_timestamp": datetime(2026, 9, 1, 10, 0),
    }]
    client = KiteOrderClient(kite_client_factory=lambda: kite)
    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())):
        trades = await client.get_trades()
    assert trades[0].side == Side.SELL
    assert trades[0].traded_at == _utc(10)


async def test_upstox_get_trades(monkeypatch):
    adapter = UpstoxAdapter(api_key="k", api_secret="s", redirect_uri="https://x/cb", redis=_redis(), user_id="alice")

    async def fake_get(self, url, **kwargs):
        assert url.endswith("/v2/order/trades/get-trades-for-day")
        return httpx.Response(200, json={"data": [{
            "exchange": "NSE", "tradingsymbol": "INFY", "transaction_type": "BUY", "quantity": 2,
            "order_id": "o1", "trade_id": "t1", "average_price": 1500.0,
            "exchange_timestamp": "2026-09-01 11:00:00",
        }]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    trades = await adapter.get_trades()
    assert (trades[0].symbol, trades[0].trade_id, trades[0].traded_at) == ("INFY", "t1", _utc(11))


async def test_angel_one_get_trades_dates_bare_fill_time_today(monkeypatch):
    adapter = AngelOneAdapter(api_key="k", api_secret=None, redis=_redis(), user_id="alice")

    async def fake_get(self, url, **kwargs):
        assert url.endswith("/order/v1/getTradeBook")
        return httpx.Response(200, json={"status": True, "data": [{
            "tradingsymbol": "SBIN-EQ", "exchange": "NSE", "transactiontype": "BUY", "fillsize": "3",
            "fillprice": "801.2", "orderid": "o9", "fillid": "f9", "filltime": "13:27:53",
        }]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr("backend.brokers.angel_one.today_ist", lambda: datetime(2026, 9, 1).date())
    trades = await adapter.get_trades()
    assert trades[0].symbol == "SBIN"
    assert trades[0].quantity == 3
    assert trades[0].traded_at == parse_ist(datetime(2026, 9, 1, 13, 27, 53))


async def test_connected_brokers_lists_only_active_sessions(monkeypatch):
    from backend.brokers.protocol import BrokerSessionState
    from backend.journal import sync

    class _A:
        def __init__(self, state):
            self._state = state

        async def state(self):
            return self._state

    states = {"kite": BrokerSessionState.NEEDS_LOGIN, "upstox": BrokerSessionState.ACTIVE,
              "angel_one": BrokerSessionState.UNCONFIGURED}
    monkeypatch.setattr(sync, "get_broker_adapter", AsyncMock(side_effect=lambda b, *a: _A(states[b])))
    assert await sync.connected_brokers(None, None, "alice") == ["upstox"]
