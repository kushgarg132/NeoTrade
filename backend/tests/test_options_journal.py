"""Options in the journal and guardrails: every round trip knows whether it
was a stock, call, put or future; the summary and findings keep options
apart; and the options guardrails fire on the user's own limits."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.guardrails.rules import evaluate
from backend.journal.insights import MIN_TRIPS, build_insights
from backend.journal.roundtrips import build_round_trips, instrument_kind, underlying_of
from backend.routers.journal import _by_kind

T0 = datetime(2026, 9, 28, 4, 0, tzinfo=timezone.utc)  # 09:30 IST


@pytest.mark.parametrize("symbol,exchange,kind", [
    ("NIFTY24OCT25000CE", "NFO", "CALL"),
    ("BANKNIFTY2410352000PE", "NFO", "PUT"),
    ("NIFTY 25100 CE 30 SEP 25", "NSE_FO", "CALL"),  # a broker that spaces the parts
    ("RELIANCE24OCTFUT", "NFO", "FUTURE"),
    ("RELIANCE", "NSE", "STOCK"),
    ("ACE", "NSE", "STOCK"),        # ends in CE, but no strike before it
    ("SOMEFNO", "NFO", "FUTURE"),   # F&O exchange, no suffix
])
def test_instrument_kind(symbol, exchange, kind):
    assert instrument_kind(symbol, exchange) == kind


def test_underlying_of():
    assert underlying_of("BANKNIFTY2410352000PE") == "BANKNIFTY"
    assert underlying_of("M&M24OCTFUT") == "M&M"
    assert underlying_of("RELIANCE") == "RELIANCE"


def _fill(i, symbol, side, qty, price, minutes, exchange="NFO"):
    return {"_id": f"f{i}", "broker": "kite", "exchange": exchange, "symbol": symbol,
            "side": side, "quantity": qty, "price": price, "traded_at": T0 + timedelta(minutes=minutes)}


def test_round_trips_carry_kind_and_underlying():
    trips = build_round_trips([
        _fill(1, "NIFTY24OCT25000CE", "SELL", 75, 120.0, 0),
        _fill(2, "NIFTY24OCT25000CE", "BUY", 75, 90.0, 30),
        _fill(3, "SBIN", "BUY", 10, 800.0, 5, exchange="NSE"),
    ])
    option = next(t for t in trips if t["symbol"].startswith("NIFTY"))
    assert option["kind"] == "CALL" and option["underlying"] == "NIFTY"
    assert option["direction"] == "SHORT" and option["pnl"] == pytest.approx(75 * 30)
    assert next(t for t in trips if t["symbol"] == "SBIN")["kind"] == "STOCK"


def _trip(i, kind, direction, pnl, minutes=0, closed_after=10, underlying="NIFTY", qty=75.0):
    opened = T0 + timedelta(minutes=minutes)
    suffix = {"CALL": "25000CE", "PUT": "25000PE", "FUTURE": "FUT", "STOCK": ""}[kind]
    return {"id": f"t{i}", "symbol": f"{underlying}{suffix}", "kind": kind, "underlying": underlying,
            "direction": direction, "quantity": qty, "entry_price": 100.0, "pnl": pnl,
            "opened_at": opened, "closed_at": None if closed_after is None else opened + timedelta(minutes=closed_after)}


def test_summary_splits_stocks_options_and_futures():
    split = _by_kind([_trip(1, "CALL", "LONG", -500), _trip(2, "PUT", "SHORT", 300),
                      _trip(3, "STOCK", "LONG", 200), _trip(4, "FUTURE", "LONG", -100)])
    assert split["options"] == {"trips": 2, "pnl": -200.0, "wins": 1}
    assert split["stocks"] == {"trips": 1, "pnl": 200.0, "wins": 1}
    assert split["futures"]["trips"] == 1


def test_options_findings_separate_buying_from_selling():
    trips = ([_trip(i, "CALL", "LONG", -400, minutes=i * 20) for i in range(MIN_TRIPS)]
             + [_trip(10 + i, "PUT", "SHORT", 250, minutes=i * 20 + 5) for i in range(MIN_TRIPS)]
             + [_trip(20 + i, "STOCK", "LONG", 100, minutes=i * 20 + 7) for i in range(MIN_TRIPS)])
    kinds = {f["kind"]: f for f in build_insights(trips)}
    assert kinds["option_buying"]["pnl"] == -400 * MIN_TRIPS
    assert kinds["option_selling"]["pnl"] == 250 * MIN_TRIPS
    assert {f["title"] for f in build_insights(trips) if f["kind"] == "instrument"} == {"Trading Options", "Trading Stocks"}


def test_option_trade_limit():
    trips = [_trip(i, "CALL", "LONG", 0, minutes=i) for i in range(4)] + [_trip(9, "STOCK", "LONG", 0)]
    rules = [b["rule"] for b in evaluate(trips, 0.0, {"max_option_trades_per_day": 3})]
    assert rules == ["max_option_trades"]
    assert evaluate(trips, 0.0, {"max_option_trades_per_day": 4}) == []


def test_option_lot_limit_uses_known_lot_sizes_only():
    big = _trip(1, "CALL", "LONG", 0, qty=300.0)  # 4 lots of 75
    breaches = evaluate([big], 0.0, {"max_option_lots": 2}, lot_sizes={big["symbol"]: 75})
    assert [b["rule"] for b in breaches] == ["max_option_lots"]
    assert "4 lots" in breaches[0]["detail"]
    assert evaluate([big], 0.0, {"max_option_lots": 2}) == []  # lot size unknown: not checked


def test_a_naked_short_option_warns_and_a_hedged_one_does_not():
    prefs = {"warn_naked_options": True}
    naked = _trip(1, "PUT", "SHORT", None, closed_after=None)
    assert [b["rule"] for b in evaluate([naked], 0.0, prefs)] == ["naked_option"]

    hedge = _trip(2, "PUT", "LONG", None, minutes=-5, closed_after=None)
    short = _trip(3, "PUT", "SHORT", None, minutes=0, closed_after=None)
    assert evaluate([hedge, short], 0.0, prefs) == []

    other_underlying = _trip(4, "PUT", "LONG", None, minutes=-5, closed_after=None, underlying="BANKNIFTY")
    assert [b["rule"] for b in evaluate([other_underlying, short], 0.0, prefs)] == ["naked_option"]
    assert evaluate([naked], 0.0, {}) == []  # off by default
