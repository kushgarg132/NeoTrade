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
"""

from datetime import timedelta

from backend.engine.session import IST


def _clock(dt) -> str:
    return dt.astimezone(IST).strftime("%H:%M")


def _inr(value: float) -> str:
    return f"₹{abs(value):,.0f}"


def evaluate(trips: list[dict], day_pnl: float, prefs: dict) -> list[dict]:
    breaches = []

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
                "detail": f"Your cooldown runs until {_clock(until)} IST.",
            })
            for other in opened:
                if start < other["opened_at"] < until:
                    breaches.append({
                        "key": f"cooldown_broken:{other['id']}", "rule": "cooldown_broken",
                        "title": "Trade opened during your cooldown",
                        "detail": f"{other['symbol']} at {_clock(other['opened_at'])} IST, "
                                  f"cooldown ran until {_clock(until)} IST.",
                    })
    return breaches
