"""FY capital-gains report for the user's own account: realised gains split
short/long term, estimated tax, and what to do about it. Pure. Estimates."""

import math
from datetime import date, timedelta

from backend.engine.session import IST

STCG_RATE, LTCG_RATE = 0.20, 0.125  # rates effective 2024-07-23
LTCG_EXEMPTION = 125_000
GRANDFATHER_DATE = date(2018, 2, 1)  # holdings bought before this have a stepped-up cost basis
TURNING_LONG_DAYS = 60


def current_fy(today: date) -> int:
    return today.year if today.month >= 4 else today.year - 1


def fy_bounds(fy: int) -> tuple[date, date]:
    return date(fy, 4, 1), date(fy + 1, 3, 31)


def long_from(buy: date) -> date:
    """The first day a sale is long-term: held more than 12 months, counted
    in months, not 365 days (a year spanning 29 Feb has 366)."""
    try:
        anniversary = buy.replace(year=buy.year + 1)
    except ValueError:  # bought 29 Feb
        anniversary = date(buy.year + 1, 2, 28)
    return anniversary + timedelta(days=1)


def is_long(buy: date, sell: date) -> bool:
    return sell >= long_from(buy)


def days_to_long(buy: date, today: date) -> int:
    return max((long_from(buy) - today).days, 0)


def _set_off(short: float, long: float) -> tuple[float, float]:
    """A short loss offsets long gains too; a long loss offsets only long gains."""
    return (0.0, long + short) if short < 0 else (short, long)


def est_tax(short_gain: float, long_gain: float) -> float:
    short, long = _set_off(short_gain, long_gain)
    return STCG_RATE * max(short, 0) + LTCG_RATE * max(long - LTCG_EXEMPTION, 0)


def report(trades: list[dict], held: dict[str, float], prices: dict[str, float], fy: int, today: date,
           avgs: dict[str, float] | None = None) -> dict:
    """`held`/`avgs`: the broker's quantity and average price per symbol."""
    from backend.mine.lots import open_lots, realised, reconcile, unmatched
    from backend.portfolio.rebalance import charges

    start, end = fy_bounds(fy)
    avgs = avgs or {}
    rows, unknown = [], []
    for s in sorted({t["symbol"] for t in trades}):
        for r in realised(trades, s):
            if start <= r["sell_date"] <= end:
                rows.append({**r, "term": "long" if is_long(r["buy_date"], r["sell_date"]) else "short"})
        sold = sum(q for d, q, _ in unmatched(trades, s) if start <= d <= end)
        if sold > 1e-9:  # its gain is unknown: left out of the figures, said so
            unknown.append({"symbol": s, "qty": sold, "sold": True})
    short = sum(r["gain"] for r in rows if r["term"] == "short")
    long = sum(r["gain"] for r in rows if r["term"] == "long")
    used = min(max(_set_off(short, long)[1], 0.0), LTCG_EXEMPTION)
    left = LTCG_EXEMPTION - used
    fees = sum(charges(t["side"], float(t["quantity"]), float(t["price"])) for t in trades
               if start <= t["traded_at"].astimezone(IST).date() <= end)

    unrealised, pre_2018 = [], []
    for s, qty in sorted(held.items()):
        lots, unk = reconcile(open_lots(trades, s), qty, avgs.get(s))
        if unk > 1e-9:
            unknown.append({"symbol": s, "qty": unk})
        if any(d < GRANDFATHER_DATE for d, _, _ in lots):
            pre_2018.append(s)
        last = prices.get(s)
        if last is None:
            continue
        for d, q, p in lots:
            lng = is_long(d, today)
            unrealised.append({"symbol": s, "buy_date": d, "qty": q, "price": p, "last": last,
                               "gain": (last - p) * q, "term": "long" if lng else "short",
                               "days_to_long": days_to_long(d, today)})

    turning = [{"symbol": u["symbol"], "buy_date": u["buy_date"], "qty": u["qty"], "gain": u["gain"],
                "days": u["days_to_long"], "saving": (STCG_RATE - LTCG_RATE) * u["gain"]}
               for u in unrealised if u["term"] == "short" and u["gain"] > 0 and u["days_to_long"] <= TURNING_LONG_DAYS]

    # Older untracked shares (unknown) mean FIFO may have sold the wrong lot.
    doubtful = {u["symbol"] for u in unknown}
    for r in rows:
        r["uncertain"] = r["symbol"] in doubtful
    uncertain = sorted({r["symbol"] for r in rows if r["uncertain"]})

    # Loss harvest: what selling a symbol's losing lots takes off this FY's tax.
    loss: dict[str, dict] = {}
    for u in unrealised:
        if u["gain"] < 0:
            e = loss.setdefault(u["symbol"], {"symbol": u["symbol"], "qty": 0.0, "loss": 0.0, "short": 0.0, "long": 0.0})
            e["qty"] += u["qty"]
            e["loss"] += u["gain"]
            e[u["term"]] += u["gain"]
    base = est_tax(short, long)
    for e in loss.values():
        e["saving"] = base - est_tax(short + e.pop("short"), long + e.pop("long"))
    gain: dict[str, dict] = {}
    room = left
    for u in sorted((u for u in unrealised if u["term"] == "long" and u["gain"] > 0), key=lambda u: -u["gain"]):
        per_share = u["gain"] / u["qty"]
        n = min(u["qty"], math.floor(room / per_share + 1e-9))  # whole shares only: a lot can't be sold in part-shares
        if n <= 0:
            continue
        e = gain.setdefault(u["symbol"], {"symbol": u["symbol"], "qty": 0.0, "gain": 0.0})
        e["qty"] += n
        e["gain"] += per_share * n
        room -= per_share * n

    return {
        "realised": {"short_gain": short, "long_gain": long, "exemption_used": used, "exemption_left": left,
                     "charges": fees, "est_tax": base, "rows": rows, "uncertain": uncertain},
        "unrealised": unrealised,
        "turning_long": turning,
        "harvest": {"loss": [e for e in loss.values() if e["saving"] > 0.005], "gain": list(gain.values())},
        "unknown": unknown,
        "pre_2018": pre_2018,
        "has_history": bool(trades),
    }
