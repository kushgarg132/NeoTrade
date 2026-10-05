from datetime import date

import pytest

from backend.portfolio.rebalance import target_gaps, target_weights, universe


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
