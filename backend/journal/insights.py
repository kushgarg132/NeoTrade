"""Behaviour findings over a user's own closed round trips. Pure, no I/O.

Each finding is one group of the user's trades (e.g. "trades opened after
two losses in a row that day") set against every other closed trade, so the
number means something on its own. A group needs MIN_TRIPS trades before it
is reported at all -- three unlucky trades are not a habit.

These describe what the user did. They never say what to trade.
"""

from collections import defaultdict
from datetime import time

from backend.engine.session import IST

MIN_TRIPS = 5
LOSS_STREAK = 2
LATE_TRADE_NUMBER = 4  # the 4th and later trades opened on one day
SIZE_UP_RATIO = 1.25
HOLD_RATIO = 1.5

_BUCKETS = [
    (time(9, 30), "Opened 09:15–09:30"),
    (time(11, 0), "Opened 09:30–11:00"),
    (time(13, 0), "Opened 11:00–13:00"),
    (time(14, 30), "Opened 13:00–14:30"),
    (time(23, 59, 59), "Opened after 14:30"),
]
_WEEKDAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]


def _ist(dt):
    return dt.astimezone(IST)


def _bucket(trip) -> str:
    opened = _ist(trip["opened_at"]).time()
    return next(label for limit, label in _BUCKETS if opened < limit)


def _notional(trip) -> float:
    return trip["quantity"] * trip["entry_price"]


def _stats(trips: list[dict]) -> dict:
    pnl = sum(t["pnl"] for t in trips)
    return {
        "trips": len(trips),
        "pnl": round(pnl, 2),
        "avg_pnl": round(pnl / len(trips), 2) if trips else 0.0,
        "win_rate": round(sum(t["pnl"] > 0 for t in trips) / len(trips), 4) if trips else 0.0,
    }


def _finding(kind: str, title: str, group: list[dict], closed: list[dict], note: str = "") -> dict:
    ids = {t["id"] for t in group}
    rest = [t for t in closed if t["id"] not in ids]
    baseline = _stats(rest)
    return {
        "kind": kind, "title": title, "note": note, **_stats(group),
        "baseline_win_rate": baseline["win_rate"], "baseline_avg_pnl": baseline["avg_pnl"],
    }


def _extremes(kind: str, groups: dict[str, list[dict]], closed: list[dict]) -> list[dict]:
    """The worst group if it lost money and the best if it made money --
    listing every bucket would bury the two that matter."""
    sized = {label: g for label, g in groups.items() if len(g) >= MIN_TRIPS}
    if len(sized) < 2:
        return []
    ranked = sorted(sized.items(), key=lambda item: sum(t["pnl"] for t in item[1]))
    found = []
    worst_label, worst = ranked[0]
    if sum(t["pnl"] for t in worst) < 0:
        found.append(_finding(kind, worst_label, worst, closed))
    best_label, best = ranked[-1]
    if sum(t["pnl"] for t in best) > 0:
        found.append(_finding(kind, best_label, best, closed))
    return found


def _same_day_context(closed: list[dict]):
    """For each trip: how many losses in a row had closed earlier that IST
    day when it opened, whether the last one was a loss, and its open-order
    number that day."""
    by_day = defaultdict(list)
    for t in closed:
        by_day[_ist(t["opened_at"]).date()].append(t)

    context = {}
    for day_trips in by_day.values():
        day_trips.sort(key=lambda t: t["opened_at"])
        for number, trip in enumerate(day_trips, start=1):
            before = sorted(
                (t for t in day_trips if t["closed_at"] <= trip["opened_at"] and t is not trip),
                key=lambda t: t["closed_at"],
            )
            streak = 0
            for t in reversed(before):
                if t["pnl"] >= 0:
                    break
                streak += 1
            context[trip["id"]] = {"streak": streak, "after_loss": streak > 0, "number": number}
    return context


def build_insights(trips: list[dict]) -> list[dict]:
    closed = [t for t in trips if t["pnl"] is not None]
    if len(closed) < MIN_TRIPS:
        return []

    findings = []

    by_bucket, by_weekday = defaultdict(list), defaultdict(list)
    for t in closed:
        by_bucket[_bucket(t)].append(t)
        by_weekday[_WEEKDAYS[_ist(t["opened_at"]).weekday()]].append(t)
    findings += _extremes("time_of_day", by_bucket, closed)
    findings += _extremes("weekday", {f"Opened on {k}": v for k, v in by_weekday.items()}, closed)

    context = _same_day_context(closed)

    after_streak = [t for t in closed if context[t["id"]]["streak"] >= LOSS_STREAK]
    if len(after_streak) >= MIN_TRIPS:
        findings.append(_finding(
            "after_losses", f"Opened after {LOSS_STREAK} or more losses in a row that day", after_streak, closed,
        ))

    late = [t for t in closed if context[t["id"]]["number"] >= LATE_TRADE_NUMBER]
    if len(late) >= MIN_TRIPS:
        findings.append(_finding("trade_count", f"Trade number {LATE_TRADE_NUMBER} or later in a day", late, closed))

    after_loss = [t for t in closed if context[t["id"]]["after_loss"]]
    other = [t for t in closed if not context[t["id"]]["after_loss"]]
    if len(after_loss) >= MIN_TRIPS and other:
        after_size = sum(map(_notional, after_loss)) / len(after_loss)
        usual_size = sum(map(_notional, other)) / len(other)
        if usual_size and after_size / usual_size >= SIZE_UP_RATIO:
            findings.append(_finding(
                "size_after_loss", "Position size right after a loss", after_loss, closed,
                note=f"{after_size / usual_size:.1f}× your usual position size",
            ))

    winners = [t for t in closed if t["pnl"] > 0]
    losers = [t for t in closed if t["pnl"] < 0]
    if len(winners) >= MIN_TRIPS and len(losers) >= MIN_TRIPS:
        def hold(group):
            return sum((t["closed_at"] - t["opened_at"]).total_seconds() for t in group) / len(group)

        win_hold, loss_hold = hold(winners), hold(losers)
        if win_hold and loss_hold / win_hold >= HOLD_RATIO:
            findings.append(_finding(
                "hold_time", "Losing trades held longer than winners", losers, closed,
                note=f"Losers held {loss_hold / win_hold:.1f}× as long as winners on average",
            ))

    by_tag = defaultdict(list)
    for t in closed:
        for tag in t.get("tags") or []:
            by_tag[tag].append(t)
    for tag, group in sorted(by_tag.items()):
        if len(group) >= MIN_TRIPS:
            findings.append(_finding("tag", f"Tagged “{tag}”", group, closed))

    findings.sort(key=lambda f: f["pnl"])  # costliest first
    return findings
