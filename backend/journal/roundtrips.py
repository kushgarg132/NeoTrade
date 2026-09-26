"""Groups raw executions into round trips: flat -> position -> flat, per
(broker, exchange, symbol). Pure, no I/O. A fill that crosses zero (long 10,
sell 15) closes the first trip and opens a short one with the remainder.

P&L here is gross -- brokerage, STT and exchange charges are not in any
broker's trade book, so they are not subtracted.
"""

from backend.engine.session import IST


def _new_trip(trade: dict, direction: str) -> dict:
    return {
        "id": trade["_id"], "broker": trade["broker"], "exchange": trade["exchange"],
        "symbol": trade["symbol"], "direction": direction, "opened_at": trade["traded_at"],
        "closed_at": None, "entry_qty": 0.0, "entry_value": 0.0, "exit_qty": 0.0,
        "exit_value": 0.0, "trade_ids": [],
    }


def _finish(trip: dict) -> dict:
    entry_avg = trip["entry_value"] / trip["entry_qty"] if trip["entry_qty"] else 0.0
    exit_avg = trip["exit_value"] / trip["exit_qty"] if trip["exit_qty"] else None
    pnl = None
    if trip["closed_at"] is not None:
        sign = 1 if trip["direction"] == "LONG" else -1
        pnl = round(sign * (trip["exit_value"] - trip["entry_value"]), 2)
    closed = trip["closed_at"]
    return {
        "id": trip["id"], "broker": trip["broker"], "exchange": trip["exchange"],
        "symbol": trip["symbol"], "direction": trip["direction"],
        "quantity": trip["entry_qty"], "entry_price": round(entry_avg, 4),
        "exit_price": round(exit_avg, 4) if exit_avg is not None else None,
        "opened_at": trip["opened_at"], "closed_at": closed, "pnl": pnl,
        "day": closed.astimezone(IST).date().isoformat() if closed else None,
        "trade_ids": trip["trade_ids"],
    }


def build_round_trips(trades: list[dict]) -> list[dict]:
    """`trades` are journal documents (see store.py). Returns closed trips
    and any still-open one per symbol (pnl None), oldest first."""
    groups: dict[tuple, list[dict]] = {}
    for t in trades:
        groups.setdefault((t["broker"], t["exchange"], t["symbol"]), []).append(t)

    trips = []
    for rows in groups.values():
        rows.sort(key=lambda t: (t["traded_at"], t["_id"]))
        position = 0.0
        trip = None
        for t in rows:
            buy = t["side"] == "BUY"
            remaining = float(t["quantity"])
            while remaining > 1e-9:
                if abs(position) < 1e-9:
                    trip = _new_trip(t, "LONG" if buy else "SHORT")
                opening = (position >= 0) == buy or abs(position) < 1e-9
                take = remaining if opening else min(remaining, abs(position))
                if opening:
                    trip["entry_qty"] += take
                    trip["entry_value"] += take * t["price"]
                else:
                    trip["exit_qty"] += take
                    trip["exit_value"] += take * t["price"]
                position += take if buy else -take
                remaining -= take
                if t["_id"] not in trip["trade_ids"]:
                    trip["trade_ids"].append(t["_id"])
                if not opening and abs(position) < 1e-9:
                    trip["closed_at"] = t["traded_at"]
                    trips.append(_finish(trip))
                    trip = None
        if trip is not None:
            trips.append(_finish(trip))

    trips.sort(key=lambda r: r["opened_at"])
    return trips


def daily_pnl(trips: list[dict]) -> list[dict]:
    """One row per IST day a trip closed on: the calendar view."""
    days: dict[str, dict] = {}
    for trip in trips:
        if trip["pnl"] is None:
            continue
        row = days.setdefault(trip["day"], {"day": trip["day"], "pnl": 0.0, "trips": 0, "wins": 0})
        row["pnl"] = round(row["pnl"] + trip["pnl"], 2)
        row["trips"] += 1
        row["wins"] += trip["pnl"] > 0
    return sorted(days.values(), key=lambda r: r["day"])
