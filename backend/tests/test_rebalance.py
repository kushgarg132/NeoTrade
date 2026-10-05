from datetime import date

import pytest

from backend.portfolio.rebalance import (
    DEFAULT_TARGETS, plan_rebalance, sell_tax, target_gaps, target_weights, universe,
)


def h(symbol, value, price=100.0, kind="STOCK", sector="IT"):
    return {"symbol": symbol, "kind": kind, "sector": sector, "quantity": value / price,
            "last_price": price, "close_price": price}


def test_equal_weight_splits_evenly():
    w = target_weights(universe([h("A", 600), h("B", 300), h("C", 100)])[0], {"rule": "equal", "overrides": {}}, 1000)
    assert w == pytest.approx({"A": 1 / 3, "B": 1 / 3, "C": 1 / 3})


def test_cap_trims_and_redistributes():
    names = universe([h("A", 500, sector="X"), h("B", 300, sector="Y"), h("C", 200, sector="Z")])[0]
    w = target_weights(names, {"rule": "cap", "max_stock_pct": 40, "max_sector_pct": 100, "overrides": {}}, 1000)
    assert w["A"] == pytest.approx(0.40)
    assert w["B"] == pytest.approx(0.30 + 0.10 * 0.6) and w["C"] == pytest.approx(0.20 + 0.10 * 0.4)


def test_sector_cap_applies_and_etfs_are_exempt():
    names = universe([h("A", 400), h("B", 400), h("E", 200, kind="ETF", sector=None)])[0]
    w = target_weights(names, {"rule": "cap", "max_stock_pct": 100, "max_sector_pct": 50, "overrides": {}}, 1000)
    assert w["A"] + w["B"] == pytest.approx(0.50) and w["E"] == pytest.approx(0.50)


def test_override_beats_rule_and_unknown_override_is_ignored():
    names = universe([h("A", 500), h("B", 500)])[0]
    w = target_weights(names, {"rule": "equal", "overrides": {"A": 20, "ZZZ": 50}}, 1000)
    assert w == pytest.approx({"A": 0.20, "B": 0.80})


def test_all_clipped_leaves_cash_and_terminates():
    names = universe([h("A", 500, sector="X"), h("B", 500, sector="X")])[0]
    w = target_weights(names, {"rule": "cap", "max_stock_pct": 30, "max_sector_pct": 100, "overrides": {}}, 1000)
    assert sum(w.values()) == pytest.approx(0.60)


def test_funds_unpriced_and_zero_quantity_are_excluded():
    rows = [h("A", 100), {**h("MF1", 100), "kind": "MF"},
            {**h("U", 100), "last_price": None, "close_price": None}, {**h("Z", 100), "quantity": 0}]
    names, excluded = universe(rows)
    assert [n["symbol"] for n in names] == ["A"]
    assert {e["symbol"] for e in excluded} == {"MF1", "U", "Z"}


def test_target_gaps_are_weight_differences():
    gaps, total, _ = target_gaps([h("A", 750), h("B", 250)], {"rule": "equal", "overrides": {}})
    assert total == 1000 and gaps == pytest.approx({"A": -0.25, "B": 0.25})


TODAY = date(2026, 10, 5)
EQUAL = {"rule": "equal", "overrides": {}}


def test_new_money_used_before_any_sell():
    out = plan_rebalance([h("A", 60_000), h("B", 40_000)], [], EQUAL, 20_000, {}, TODAY)
    assert all(t["side"] == "BUY" for t in out["trades"]) and [t["symbol"] for t in out["trades"]] == ["B"]


def test_overweight_is_sold_to_fund_buys_sells_listed_first():
    out = plan_rebalance([h("A", 80_000), h("B", 20_000)], [], EQUAL, 0, {}, TODAY)
    assert [(t["symbol"], t["side"]) for t in out["trades"]] == [("A", "SELL"), ("B", "BUY")]
    assert out["trades"][0]["quantity"] == 300


def test_buys_scaled_when_cash_short():
    out = plan_rebalance([h("A", 10_000), h("B", 10_000)],
                         [{"symbol": "C", "price": 100.0, "kind": "STOCK", "sector": None}], EQUAL, 0, {}, TODAY)
    spent = sum(t["value"] + t["charges"] for t in out["trades"] if t["side"] == "BUY")
    got = sum(t["value"] - t["charges"] for t in out["trades"] if t["side"] == "SELL")
    assert any(t["symbol"] == "C" for t in out["trades"]) and spent <= got + 1e-6


def test_share_dearer_than_slot_is_skipped():
    out = plan_rebalance([h("A", 9_000), h("B", 1_000, price=5_000)], [], EQUAL, 0, {}, TODAY)
    assert {"symbol": "B", "reason": "one share costs more than its slot"} in out["skipped"]


def test_tiny_trade_dropped_for_charges():
    out = plan_rebalance([h("A", 5_010, price=1.0), h("B", 4_990, price=1.0)], [], EQUAL, 0, {}, TODAY)
    assert out["trades"] == [] and any(s["reason"] == "charges above 1% of the trade" for s in out["skipped"])


def test_sell_tax_splits_short_and_long_fifo():
    lots = [(date(2025, 1, 1), 10, 50.0), (date(2026, 6, 1), 10, 80.0)]
    t = sell_tax(15, 100.0, lots, TODAY)
    assert t["long_gain"] == pytest.approx(500) and t["short_gain"] == pytest.approx(100)
    assert t["unknown_qty"] == 0 and t["est_tax"] == pytest.approx(0.125 * 500 + 0.20 * 100)


def test_sell_tax_with_no_journal_is_unknown():
    t = sell_tax(5, 100.0, [], TODAY)
    assert t["unknown_qty"] == 5 and t["est_tax"] is None


def test_sell_tax_loss_gives_no_tax():
    t = sell_tax(10, 40.0, [(date(2026, 6, 1), 10, 80.0)], TODAY)
    assert t["short_gain"] == pytest.approx(-400) and t["est_tax"] == 0


def test_weight_after_never_exceeds_100():
    out = plan_rebalance([h("A", 70_000), h("B", 30_000)], [], DEFAULT_TARGETS, 5_000, {}, TODAY)
    assert sum(t["weight_after"] for t in out["trades"]) <= 100 + 1e-6
