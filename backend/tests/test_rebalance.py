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


def test_plan_reports_the_share_caps_leave_uninvested():
    rows = [h("A", 50_000, sector="X"), h("B", 30_000, sector="Y"), h("C", 20_000, sector="Z")]
    out = plan_rebalance(rows, [], DEFAULT_TARGETS, 0, {}, TODAY)
    assert out["uninvested_pct"] == pytest.approx(55.0)
    assert plan_rebalance(rows, [], EQUAL, 0, {}, TODAY)["uninvested_pct"] == pytest.approx(0.0)


def v(symbol, value, verdict="HOLD", score=None, sector="IT", kind="STOCK"):
    row = h(symbol, value, sector=sector, kind=kind)
    row.update(verdict=verdict, score=None if score is None else {"final": score})
    return row


CONVICTION = {"rule": "conviction", "max_stock_pct": 100, "max_sector_pct": 100, "overrides": {}}


def test_conviction_add_outweighs_hold_by_score():
    names = universe([v("A", 500, "ADD", 0.8), v("B", 500, "HOLD")])[0]
    w = target_weights(names, CONVICTION, 1000)
    assert w["A"] / w["B"] == pytest.approx(1.8) and sum(w.values()) == pytest.approx(1.0)


def test_conviction_sell_gets_zero_and_never_absorbs():
    names = universe([v("A", 400, "SELL", 0.7, sector="X"), v("B", 300, "ADD", 0.9, sector="Y"),
                      v("C", 300, "HOLD", sector="Z")])[0]
    w = target_weights(names, {**CONVICTION, "max_stock_pct": 40}, 1000)
    assert w["A"] == 0 and w["B"] == pytest.approx(0.40) and w["C"] == pytest.approx(0.40)  # 20% left as cash


def test_conviction_all_sell_is_cash():
    names = universe([v("A", 500, "SELL", 0.6), v("B", 500, "SELL", 0.9)])[0]
    assert sum(target_weights(names, CONVICTION, 1000).values()) == 0


def test_conviction_ai_pick_weighted_watchlist_neutral():
    out = plan_rebalance([v("A", 10_000, "HOLD", sector="X")],
                         [{"symbol": "P", "price": 100.0, "source": "ai", "score": 0.5},
                          {"symbol": "W", "price": 100.0, "source": "watchlist", "score": None}],
                         CONVICTION, 0, {}, TODAY)
    target = {t["symbol"]: t["target_weight"] for t in out["trades"]}
    assert target["P"] / target["W"] == pytest.approx(1.5)


def test_conviction_missing_score_is_neutral():
    names = universe([v("A", 200, "ADD", None), v("B", 800, "HOLD")])[0]
    assert target_weights(names, CONVICTION, 1000) == pytest.approx({"A": 0.5, "B": 0.5})


def test_conviction_caps_and_overrides_still_apply():
    names = universe([v("A", 100, "ADD", 1.0, sector="X"), v("B", 600, "HOLD", sector="Y"),
                      v("C", 300, "HOLD", sector="Z")])[0]
    w = target_weights(names, {**CONVICTION, "max_stock_pct": 45, "overrides": {"C": 10}}, 1000)
    assert w["C"] == pytest.approx(0.10) and w["A"] == pytest.approx(0.45) and w["B"] == pytest.approx(0.45)
