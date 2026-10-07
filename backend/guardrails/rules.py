"""The user's own limits, checked against their real broker activity for the
day. Pure, no I/O: `evaluate` takes today's round trips and the broker's own
day P&L and returns every breach. Each breach carries a stable `key` so the
monitor alerts once per breach, not once per poll.

Rules, all set by the user in Settings (0 means off):
- daily loss: broker day P&L at or below -daily_loss_limit (the same limit
  the engine's kill-switch uses -- one number, one meaning).
- trade count: more than max_trades_per_day round trips opened today.
- cooldown: after cooldown_after_losses losses in a row, any trade opened
  within cooldown_minutes of the last one closing.
- option trades: more than max_option_trades_per_day options round trips
  opened today.
- option lots: an options trade larger than max_option_lots lots (only
  where the contract's lot size is known from the broker's NFO dump).
- naked short option (warn_naked_options): an option sold while no bought
  option on the same underlying was open -- a sold option's loss has no
  fixed ceiling unless a bought one caps it.
"""

from datetime import timedelta

from backend.engine.session import IST, clock


def _inr(value: float) -> str:
    return f"₹{abs(value):,.0f}"


_OPTIONS = ("CALL", "PUT")


def _is_hedged(short: dict, trips: list[dict]) -> bool:
    # ponytail: any bought option on the same underlying open when the short
    # opened counts as a hedge -- strike, expiry and call/put are not
    # matched, so a mismatched pair passes. Match them when that matters.
    return any(
        t is not short and t.get("kind") in _OPTIONS and t["direction"] == "LONG"
        and t.get("underlying") == short.get("underlying")
        and t["opened_at"] <= short["opened_at"]
        and (t["closed_at"] is None or t["closed_at"] > short["opened_at"])
        for t in trips
    )


def _option_breaches(trips: list[dict], prefs: dict, lot_sizes: dict) -> list[dict]:
    breaches = []
    options = sorted((t for t in trips if t.get("kind") in _OPTIONS), key=lambda t: t["opened_at"])

    max_trades = int(prefs.get("max_option_trades_per_day") or 0)
    if max_trades and len(options) > max_trades:
        breaches.append({
            "key": "max_option_trades", "rule": "max_option_trades",
            "title": "Options trade limit passed",
            "detail": f"{len(options)} options trades opened today against your limit of {max_trades}.",
        })

    max_lots = int(prefs.get("max_option_lots") or 0)
    for trip in options:
        lot = lot_sizes.get(trip["symbol"])
        if max_lots and lot and trip["quantity"] / lot > max_lots:
            breaches.append({
                "key": f"option_lots:{trip['id']}", "rule": "max_option_lots",
                "title": "Options position larger than your lot limit",
                "detail": f"{trip['symbol']}: {trip['quantity'] / lot:g} lots against your limit of {max_lots}.",
            })
        if prefs.get("warn_naked_options") and trip["direction"] == "SHORT" and not _is_hedged(trip, trips):
            breaches.append({
                "key": f"naked_option:{trip['id']}", "rule": "naked_option",
                "title": "Option sold without a hedge",
                "detail": f"{trip['symbol']} sold at {clock(trip['opened_at'])} IST with no bought "
                          f"{trip.get('underlying')} option open to cap the loss.",
            })
    return breaches


def evaluate(trips: list[dict], day_pnl: float, prefs: dict, lot_sizes: dict | None = None) -> list[dict]:
    """`lot_sizes` maps an options symbol to its contract lot size, for the
    lot limit; symbols missing from it are not checked."""
    breaches = _option_breaches(trips, prefs, lot_sizes or {})

    limit = abs(prefs.get("daily_loss_limit") or 0)
    if limit and day_pnl <= -limit:
        breaches.append({
            "key": "daily_loss", "rule": "daily_loss",
            "title": "Daily loss limit reached",
            "detail": f"Down {_inr(day_pnl)} today against your {_inr(limit)} limit. "
                      "The engine is halted for the rest of the day.",
        })

    max_trades = int(prefs.get("max_trades_per_day") or 0)
    opened = sorted(trips, key=lambda t: t["opened_at"])
    if max_trades and len(opened) > max_trades:
        breaches.append({
            "key": "max_trades", "rule": "max_trades",
            "title": "Trade limit passed",
            "detail": f"{len(opened)} trades opened today against your limit of {max_trades}.",
        })

    after = int(prefs.get("cooldown_after_losses") or 0)
    minutes = int(prefs.get("cooldown_minutes") or 0)
    if after and minutes:
        closed = sorted((t for t in trips if t["pnl"] is not None), key=lambda t: t["closed_at"])
        streak = 0
        for trip in closed:
            streak = streak + 1 if trip["pnl"] < 0 else 0
            if streak < after:
                continue
            start = trip["closed_at"]
            until = start + timedelta(minutes=minutes)
            breaches.append({
                "key": f"cooldown_start:{trip['id']}", "rule": "cooldown_start",
                "title": f"{streak} losses in a row",
                "detail": f"Your cooldown runs until {clock(until)} IST.",
            })
            for other in opened:
                if start < other["opened_at"] < until:
                    breaches.append({
                        "key": f"cooldown_broken:{other['id']}", "rule": "cooldown_broken",
                        "title": "Trade opened during your cooldown",
                        "detail": f"{other['symbol']} at {clock(other['opened_at'])} IST, "
                                  f"cooldown ran until {clock(until)} IST.",
                    })
    return breaches
