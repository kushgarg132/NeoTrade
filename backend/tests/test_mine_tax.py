from datetime import date, datetime, timezone

import pytest

from backend.engine.session import IST
from backend.mine import tax


def _t(side, sym, qty, price, at):
    return {"symbol": sym, "side": side, "quantity": qty, "price": price, "broker": "upstox", "traded_at": at}


def buy(*a):
    return _t("BUY", *a)


def sell(*a):
    return _t("SELL", *a)


def utc(y, m, d):
    return datetime(y, m, d, 10, tzinfo=timezone.utc)


def test_day_365_is_short_366_is_long():
    assert not tax.is_long(date(2025, 4, 1), date(2026, 4, 1))
    assert tax.is_long(date(2025, 4, 1), date(2026, 4, 2))


def test_long_term_is_12_months_not_365_days_across_29_feb():
    assert not tax.is_long(date(2027, 3, 1), date(2028, 3, 1))  # 366 days, exactly 12 months: short
    assert tax.is_long(date(2027, 3, 1), date(2028, 3, 2))
    assert tax.days_to_long(date(2027, 3, 1), date(2028, 2, 29)) == 2
    assert tax.long_from(date(2028, 2, 29)) == date(2029, 3, 1)


def test_fy():
    assert tax.current_fy(date(2026, 3, 31)) == 2025 and tax.current_fy(date(2026, 4, 1)) == 2026
    assert tax.fy_bounds(2026) == (date(2026, 4, 1), date(2027, 3, 31))


def test_exemption_straddle():
    assert tax.est_tax(0, 200_000) == pytest.approx(9_375)


def test_set_off_order():
    assert tax.est_tax(50_000 - 20_000, 150_000 - 10_000) == pytest.approx(6_000 + 1_875)


def test_short_loss_spills_into_long():
    assert tax.est_tax(-30_000, 200_000) == pytest.approx(0.125 * (170_000 - 125_000))


def test_ist_midnight_fill_lands_in_next_fy():
    r = tax.report([buy("A", 1, 100, utc(2025, 1, 1)), sell("A", 1, 200, datetime(2026, 3, 31, 19, 0, tzinfo=timezone.utc))],
                   {}, {}, 2026, date(2026, 4, 2))
    assert r["realised"]["long_gain"] == 100
    assert tax.report([buy("A", 1, 100, utc(2025, 1, 1)), sell("A", 1, 200, utc(2026, 3, 31))],
                      {}, {}, 2026, date(2026, 4, 2))["realised"]["long_gain"] == 0


def test_unknown_qty_excluded_and_listed():
    r = tax.report([buy("A", 6, 100, datetime(2026, 9, 1, tzinfo=IST))], {"A": 10}, {"A": 110}, 2026, date(2026, 10, 15))
    assert r["unknown"] == [{"symbol": "A", "qty": 4}]
    assert sum(u["qty"] for u in r["unrealised"]) == 6


def test_no_history_flag():
    assert tax.report([], {"A": 10}, {"A": 100}, 2026, date(2026, 10, 15))["has_history"] is False


def test_turning_long_saving():
    today = date(2026, 10, 15)
    r = tax.report([buy("A", 100, 100, datetime(2025, 11, 3, tzinfo=IST))], {"A": 100}, {"A": 200}, 2026, today)
    t = r["turning_long"][0]
    assert t["days"] == 20  # 346 days old, long from day 366
    assert t["saving"] == pytest.approx(750)


def test_harvest_loss_and_gain_fill_exemption():
    today = date(2026, 10, 15)
    # C: a 1,000 short gain already booked this FY, for B's loss to offset.
    r = tax.report([buy("A", 10, 100, datetime(2024, 1, 1, tzinfo=IST)), buy("B", 10, 100, datetime(2026, 8, 1, tzinfo=IST)),
                    buy("C", 1, 100, datetime(2026, 5, 1, tzinfo=IST)), sell("C", 1, 1100, datetime(2026, 6, 1, tzinfo=IST))],
                   {"A": 10, "B": 10}, {"A": 200, "B": 80}, 2026, today)
    assert r["harvest"]["loss"] == [{"symbol": "B", "qty": 10, "loss": -200, "saving": pytest.approx(40)}]
    assert r["harvest"]["gain"] == [{"symbol": "A", "qty": 10, "gain": 1000}]
    assert r["realised"]["exemption_left"] == 125_000


def test_rebalance_uses_same_rates():
    from backend.portfolio import rebalance
    assert rebalance.STCG_RATE is tax.STCG_RATE


# ---- final-review fixes (I4, I6)


def test_loss_harvest_with_nothing_to_offset_is_not_listed():
    """I6 probe: no realised gains and a 1,000 loss lot used to claim 'saves 200'."""
    r = tax.report([buy("B", 10, 100, datetime(2026, 8, 1, tzinfo=IST))], {"B": 10}, {"B": 0}, 2026, date(2026, 10, 15))
    assert r["harvest"]["loss"] == []


def test_long_loss_inside_the_exemption_saves_nothing():
    trades = [buy("A", 1, 100, datetime(2024, 1, 1, tzinfo=IST)), sell("A", 1, 50_100, datetime(2026, 5, 1, tzinfo=IST)),
              buy("B", 10, 100, datetime(2024, 2, 1, tzinfo=IST))]
    r = tax.report(trades, {"B": 10}, {"B": 50}, 2026, date(2026, 10, 15))
    assert r["realised"]["long_gain"] == 50_000 and r["harvest"]["loss"] == []


def test_long_loss_above_the_exemption_saves_ltcg():
    trades = [buy("A", 1, 100, datetime(2024, 1, 1, tzinfo=IST)), sell("A", 1, 200_100, datetime(2026, 5, 1, tzinfo=IST)),
              buy("B", 10, 100, datetime(2024, 2, 1, tzinfo=IST))]
    r = tax.report(trades, {"B": 10}, {"B": 50}, 2026, date(2026, 10, 15))
    assert r["harvest"]["loss"] == [{"symbol": "B", "qty": 10, "loss": -500, "saving": pytest.approx(0.125 * 500)}]


def test_sell_with_no_known_buy_is_listed_unknown():
    """I4: the gain of a sell of pre-journal shares used to vanish without a note."""
    r = tax.report([sell("B", 5, 150, datetime(2026, 6, 1, tzinfo=IST))], {}, {}, 2026, date(2026, 10, 15))
    assert r["unknown"] == [{"symbol": "B", "qty": 5, "sold": True}]


def test_realised_rows_uncertain_when_older_shares_are_untracked():
    """I4: 10 bought 2022 (not imported) + 10 in 2025, sell 10 in 2026: FIFO picks the wrong lot."""
    trades = [buy("A", 10, 100, datetime(2025, 6, 1, tzinfo=IST)), sell("A", 10, 150, datetime(2026, 6, 1, tzinfo=IST))]
    r = tax.report(trades, {"A": 10}, {"A": 150}, 2026, date(2026, 10, 15), {"A": 50})
    assert r["realised"]["rows"][0]["uncertain"] is True and r["realised"]["uncertain"] == ["A"]
    assert r["unknown"] == [{"symbol": "A", "qty": 10}]
