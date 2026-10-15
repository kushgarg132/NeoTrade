"""FY capital-gains report for the user's own account: realised gains split
short/long term, estimated tax, and what to do about it. Pure. Estimates."""

from datetime import date

from backend.engine.session import IST

LONG_TERM_DAYS = 365
STCG_RATE, LTCG_RATE = 0.20, 0.125  # rates effective 2024-07-23
LTCG_EXEMPTION = 125_000
GRANDFATHER_DATE = date(2018, 2, 1)  # holdings bought before this have a stepped-up cost basis
TURNING_LONG_DAYS = 60


def current_fy(today: date) -> int:
    return today.year if today.month >= 4 else today.year - 1


def fy_bounds(fy: int) -> tuple[date, date]:
    return date(fy, 4, 1), date(fy + 1, 3, 31)


def is_long(buy: date, sell: date) -> bool:
    return (sell - buy).days > LONG_TERM_DAYS


def _set_off(short: float, long: float) -> tuple[float, float]:
    """A short loss offsets long gains too; a long loss offsets only long gains."""
    return (0.0, long + short) if short < 0 else (short, long)


def est_tax(short_gain: float, long_gain: float) -> float:
    short, long = _set_off(short_gain, long_gain)
    return STCG_RATE * max(short, 0) + LTCG_RATE * max(long - LTCG_EXEMPTION, 0)


def report(trades: list[dict], held: dict[str, float], prices: dict[str, float], fy: int, today: date) -> dict:
    from backend.mine.lots import open_lots, realised, reconcile
    from backend.portfolio.rebalance import charges

    start, end = fy_bounds(fy)
    rows = []
    for s in sorted({t["symbol"] for t in trades}):
        for r in realised(trades, s):
            if start <= r["sell_date"] <= end:
                rows.append({**r, "term": "long" if is_long(r["buy_date"], r["sell_date"]) else "short"})
    short = sum(r["gain"] for r in rows if r["term"] == "short")
    long = sum(r["gain"] for r in rows if r["term"] == "long")
    used = min(max(_set_off(short, long)[1], 0.0), LTCG_EXEMPTION)
    left = LTCG_EXEMPTION - used
    fees = sum(charges(t["side"], float(t["quantity"]), float(t["price"])) for t in trades
               if start <= t["traded_at"].astimezone(IST).date() <= end)

    unrealised, unknown, pre_2018 = [], [], []
    for s, qty in sorted(held.items()):
        lots, unk = reconcile(open_lots(trades, s), qty)
        if unk > 1e-9:
            unknown.append({"symbol": s, "qty": unk})
        if any(d < GRANDFATHER_DATE for d, _, _ in lots):
            pre_2018.append(s)
        last = prices.get(s)
        if last is None:
            continue
        for d, q, p in lots:
            age = (today - d).days
            lng = age > LONG_TERM_DAYS
            unrealised.append({"symbol": s, "buy_date": d, "qty": q, "price": p, "last": last,
                               "gain": (last - p) * q, "term": "long" if lng else "short",
                               "days_to_long": 0 if lng else LONG_TERM_DAYS + 1 - age})

    turning = [{"symbol": u["symbol"], "buy_date": u["buy_date"], "qty": u["qty"], "gain": u["gain"],
                "days": u["days_to_long"], "saving": (STCG_RATE - LTCG_RATE) * u["gain"]}
               for u in unrealised if u["term"] == "short" and u["gain"] > 0 and u["days_to_long"] <= TURNING_LONG_DAYS]

    loss: dict[str, dict] = {}
    for u in unrealised:
        if u["gain"] < 0:
            e = loss.setdefault(u["symbol"], {"symbol": u["symbol"], "qty": 0.0, "loss": 0.0, "saving": 0.0})
            e["qty"] += u["qty"]
            e["loss"] += u["gain"]
            e["saving"] += -u["gain"] * (LTCG_RATE if u["term"] == "long" else STCG_RATE)
    gain: dict[str, dict] = {}
    room = left
    for u in sorted((u for u in unrealised if u["term"] == "long" and u["gain"] > 0), key=lambda u: -u["gain"]):
        if room <= 1e-9:
            break
        frac = min(1.0, room / u["gain"])
        e = gain.setdefault(u["symbol"], {"symbol": u["symbol"], "qty": 0.0, "gain": 0.0})
        e["qty"] += u["qty"] * frac
        e["gain"] += u["gain"] * frac
        room -= u["gain"] * frac

    return {
        "realised": {"short_gain": short, "long_gain": long, "exemption_used": used, "exemption_left": left,
                     "charges": fees, "est_tax": est_tax(short, long), "rows": rows},
        "unrealised": unrealised,
        "turning_long": turning,
        "harvest": {"loss": list(loss.values()), "gain": list(gain.values())},
        "unknown": unknown,
        "pre_2018": pre_2018,
        "has_history": bool(trades),
    }
