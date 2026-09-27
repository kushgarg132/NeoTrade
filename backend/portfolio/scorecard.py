"""How a user's real portfolio is doing: plain arithmetic over their
broker holdings, no AI and no verdicts (those are phase 3-4, see
docs/ROADMAP.md). Pure, no I/O -- backend/portfolio/service.py fetches.

Compared with NIFTY lot by lot: each share still held is traced back to the
journal buy that opened it (first in, first out), and the same rupees are
"invested" in NIFTY on that day. Holdings bought before the journal's
history began have no such date, so the comparison says how much of the
portfolio it covers instead of guessing.
"""

from collections import defaultdict
from datetime import date
from itertools import combinations
from typing import Optional

from backend.core.models import Holding
from backend.engine.session import IST

# Holdings that move together this closely are one bet, not two.
CORRELATED = 0.8
MIN_OVERLAP_DAYS = 60


def merge(holdings: list[Holding]) -> list[dict]:
    """One row per security across brokers (by ISIN, else symbol), with a
    quantity-weighted cost basis."""
    rows: dict[str, dict] = {}
    for h in holdings:
        row = rows.setdefault(h.isin or h.symbol, {
            "symbol": h.symbol, "isin": h.isin, "name": h.name, "kind": h.kind, "brokers": [],
            "quantity": 0.0, "invested": 0.0, "last_price": None, "close_price": None,
        })
        row["quantity"] += h.quantity
        row["invested"] += h.quantity * h.avg_price
        row["brokers"] = sorted({*row["brokers"], h.broker})
        row["last_price"] = row["last_price"] or h.last_price
        row["close_price"] = row["close_price"] or h.close_price
        row["name"] = row["name"] or h.name
    for row in rows.values():
        row["avg_price"] = row["invested"] / row["quantity"] if row["quantity"] else 0.0
    return list(rows.values())


def open_lots(trades: list[dict], symbol: str) -> list[tuple[date, float, float]]:
    """(IST date, quantity, price) of the journal buys still held, oldest
    first, after sells have used up the earliest ones."""
    lots: list[list] = []
    for t in sorted((t for t in trades if t["symbol"] == symbol), key=lambda t: t["traded_at"]):
        if t["side"] == "BUY":
            lots.append([t["traded_at"].astimezone(IST).date(), float(t["quantity"]), float(t["price"])])
            continue
        left = float(t["quantity"])
        while left > 1e-9 and lots:
            used = min(left, lots[0][1])
            lots[0][1] -= used
            left -= used
            if lots[0][1] <= 1e-9:
                lots.pop(0)
    return [(d, q, p) for d, q, p in lots]


def _close_on(points: list[tuple[date, float]], day: date) -> Optional[float]:
    before = [close for d, close in points if d <= day]
    return before[-1] if before else None


def _pct(part: float, whole: float) -> Optional[float]:
    return part / whole * 100 if whole else None


def build_scorecard(
    holdings: list[Holding],
    trades: list[dict],
    nifty: list[tuple[date, float]],
    sectors: dict[str, Optional[str]],
    daily_returns: dict[str, dict[date, float]],
) -> dict:
    rows = merge(holdings)
    nifty_now = nifty[-1][1] if nifty else None
    bench_invested = bench_value = bench_nifty = 0.0

    for row in rows:
        price = row["last_price"] or row["close_price"]
        row["value"] = row["quantity"] * price if price else None
        row["pnl"] = row["value"] - row["invested"] if row["value"] is not None else None
        row["pnl_pct"] = _pct(row["pnl"], row["invested"]) if row["pnl"] is not None else None
        row["day_change"] = (
            row["quantity"] * (row["last_price"] - row["close_price"])
            if row["last_price"] and row["close_price"] else None
        )
        row["sector"] = sectors.get(row["symbol"]) if row["kind"] == "STOCK" else None

        # Lots the journal can date, capped at what is actually held now.
        row["first_bought"] = row["nifty_pnl_pct"] = None
        row["covered_quantity"] = 0.0
        lots, need = [], row["quantity"]
        for day, quantity, lot_price in reversed(open_lots(trades, row["symbol"])):
            take = min(quantity, need)
            if take <= 0:
                break
            lots.append((day, take, lot_price))
            need -= take
        if lots and nifty_now and price:
            invested = value = nifty_value = 0.0
            for day, quantity, lot_price in lots:
                start = _close_on(nifty, day)
                if not start:
                    continue
                invested += quantity * lot_price
                value += quantity * price
                nifty_value += quantity * lot_price / start * nifty_now
            if invested:
                row["first_bought"] = min(d for d, _, _ in lots).isoformat()
                row["covered_quantity"] = sum(q for _, q, _ in lots)
                row["nifty_pnl_pct"] = _pct(nifty_value - invested, invested)
                bench_invested += invested
                bench_value += value
                bench_nifty += nifty_value

    priced = [r for r in rows if r["value"] is not None]
    total_value = sum(r["value"] for r in priced)
    total_invested = sum(r["invested"] for r in priced)
    for row in rows:
        row["weight_pct"] = _pct(row["value"], total_value) if row["value"] is not None else None
    rows.sort(key=lambda r: r["value"] or 0.0, reverse=True)

    weights = [r["value"] / total_value for r in priced] if total_value else []
    by_sector: dict[str, float] = defaultdict(float)
    for row in priced:
        label = row["sector"] or ("Funds & ETFs" if row["kind"] != "STOCK" else "Unclassified")
        by_sector[label] += row["value"]

    return {
        "holdings": rows,
        "totals": {
            "invested": total_invested,
            "value": total_value,
            "pnl": total_value - total_invested,
            "pnl_pct": _pct(total_value - total_invested, total_invested),
            "day_change": sum(r["day_change"] or 0.0 for r in rows),
            "count": len(rows),
            "unpriced": [r["symbol"] for r in rows if r["value"] is None],
        },
        "benchmark": {
            # Share of the invested money whose buy dates the journal knows.
            "covered_pct": _pct(bench_invested, total_invested),
            "portfolio_pct": _pct(bench_value - bench_invested, bench_invested),
            "nifty_pct": _pct(bench_nifty - bench_invested, bench_invested),
        },
        "concentration": {
            "top_symbol": rows[0]["symbol"] if priced else None,
            "top_pct": rows[0]["weight_pct"] if priced else None,
            "top5_pct": sum(sorted(weights, reverse=True)[:5]) * 100 if weights else None,
            # 1 / sum of squared weights: 10 equal holdings -> 10, one
            # holding at 90% -> barely more than 1.
            "effective_holdings": 1 / sum(w * w for w in weights) if weights else None,
            "sectors": sorted(
                ({"sector": s, "pct": v / total_value * 100} for s, v in by_sector.items()),
                key=lambda s: s["pct"], reverse=True,
            ),
            "correlated": correlated_pairs(daily_returns),
        },
    }


def correlated_pairs(daily_returns: dict[str, dict[date, float]]) -> list[dict]:
    """Pairs of holdings whose daily returns correlate at CORRELATED or more
    over the days both traded, strongest first."""
    pairs = []
    for a, b in combinations(sorted(daily_returns), 2):
        days = daily_returns[a].keys() & daily_returns[b].keys()
        if len(days) < MIN_OVERLAP_DAYS:
            continue
        xs = [daily_returns[a][d] for d in days]
        ys = [daily_returns[b][d] for d in days]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sx = sum((x - mx) ** 2 for x in xs) ** 0.5
        sy = sum((y - my) ** 2 for y in ys) ** 0.5
        if sx and sy and (corr := cov / (sx * sy)) >= CORRELATED:
            pairs.append({"a": a, "b": b, "correlation": round(corr, 2)})
    return sorted(pairs, key=lambda p: p["correlation"], reverse=True)
