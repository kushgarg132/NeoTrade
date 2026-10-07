"""Behaviour findings, checked against values computed by hand from a small
fixture journal (Phase 10's done-when)."""

from datetime import datetime, timedelta

import pytest

from backend.brokers.trades import parse_ist
from backend.journal.insights import MIN_TRIPS, build_insights

_n = 0


def _trip(day, hh, mm, pnl, minutes=10, qty=10, price=100.0, tags=()):
    global _n
    _n += 1
    opened = parse_ist(datetime(2026, 9, day, hh, mm))
    return {"id": f"t{_n}", "opened_at": opened, "closed_at": opened + timedelta(minutes=minutes),
            "pnl": pnl, "quantity": qty, "entry_price": price, "tags": list(tags)}


def _by_kind(findings, kind):
    return [f for f in findings if f["kind"] == kind]


def test_too_few_trades_says_nothing():
    assert build_insights([_trip(1, 10, 0, -5.0) for _ in range(MIN_TRIPS - 1)]) == []


def test_open_trips_are_ignored():
    trips = [_trip(1, 10, 0, 1.0) for _ in range(MIN_TRIPS - 1)] + [{**_trip(1, 11, 0, 0.0), "pnl": None}]
    assert build_insights(trips) == []


def test_time_of_day_reports_worst_and_best_bucket():
    # 2026-09-01..05 is Tue..Sat; each day: one opening-window loss, one mid-morning win.
    trips = []
    for day in range(1, 6):
        trips.append(_trip(day, 9, 16, -100.0))
        trips.append(_trip(day, 10, 0, 40.0))
    tod = _by_kind(build_insights(trips), "time_of_day")
    assert [(f["title"], f["trips"], f["pnl"], f["win_rate"]) for f in tod] == [
        ("Opened 9:15–9:30 AM", 5, -500.0, 0.0),
        ("Opened 9:30–11:00 AM", 5, 200.0, 1.0),
    ]
    assert tod[0]["baseline_win_rate"] == 1.0
    assert tod[0]["baseline_avg_pnl"] == 40.0


def test_after_losses_size_and_trade_count():
    # Five days, each: loss, loss, then a bigger losing trade (after a 2-loss streak,
    # trade number 3), then a 4th trade that wins.
    trips = []
    for day in range(1, 6):
        trips.append(_trip(day, 10, 0, -10.0))
        trips.append(_trip(day, 10, 30, -10.0))
        trips.append(_trip(day, 11, 0, -50.0, qty=30))
        trips.append(_trip(day, 11, 30, 20.0, qty=30))
    findings = build_insights(trips)

    streak = _by_kind(findings, "after_losses")[0]
    # 3rd trade (streak 2) and 4th trade (streak 3) of each day.
    assert (streak["trips"], streak["pnl"], streak["win_rate"]) == (10, -150.0, 0.5)
    assert streak["baseline_avg_pnl"] == -10.0

    late = _by_kind(findings, "trade_count")[0]
    assert (late["trips"], late["pnl"], late["win_rate"]) == (5, 100.0, 1.0)

    size = _by_kind(findings, "size_after_loss")[0]
    # after a loss: trades 2,3,4 -> notional (1000+3000+3000)/3; otherwise trade 1 -> 1000.
    assert size["trips"] == 15
    assert size["note"] == "2.3× your usual position size"


def test_losers_held_longer_than_winners():
    trips = [_trip(d, 10, 0, 50.0, minutes=10) for d in range(1, 6)]
    trips += [_trip(d, 12, 0, -30.0, minutes=40) for d in range(1, 6)]
    hold = _by_kind(build_insights(trips), "hold_time")[0]
    assert (hold["trips"], hold["pnl"]) == (5, -150.0)
    assert hold["note"] == "Losers held 4.0× as long as winners on average"


def test_tags_and_costliest_first():
    trips = [_trip(d, 10, 0, -20.0, tags=["fomo"]) for d in range(1, 6)]
    trips += [_trip(d, 12, 0, 30.0, tags=["planned"]) for d in range(1, 6)]
    trips += [_trip(1, 13, 0, 5.0, tags=["rare"])]
    findings = build_insights(trips)
    tags = {f["title"]: f for f in _by_kind(findings, "tag")}
    assert set(tags) == {"Tagged “fomo”", "Tagged “planned”"}
    assert tags["Tagged “fomo”"]["pnl"] == -100.0
    assert tags["Tagged “fomo”"]["baseline_avg_pnl"] == pytest.approx(155 / 6, abs=0.01)
    assert [f["pnl"] for f in findings] == sorted(f["pnl"] for f in findings)
