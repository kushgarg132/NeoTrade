"""Rebalance maths: target weights from a rule plus overrides, and the trades
that move a book toward them. Pure -- the router loads the snapshot, the
journal lots and the prices (docs/superpowers/specs/2026-10-05-portfolio-rebalance-design.md).

Nothing here places an order: every trade is opened as a pre-filled ticket
the user confirms.
"""

from collections import defaultdict

DEFAULT_TARGETS = {"rule": "cap", "max_stock_pct": 15, "max_sector_pct": 30, "overrides": {}}
TRADABLE = ("STOCK", "ETF")
MAX_PASSES = 10
EPS = 1e-9


def universe(holdings: list[dict]) -> tuple[list[dict], list[dict]]:
    """(names, excluded): priced STOCK/ETF holdings with a quantity; the rest
    with the reason they are left out."""
    names, excluded = [], []
    for row in holdings:
        price = row.get("last_price") or row.get("close_price")
        if row.get("kind") not in TRADABLE:
            excluded.append({"symbol": row["symbol"], "reason": "mutual funds are not rebalanced"})
        elif not price or price <= 0:
            excluded.append({"symbol": row["symbol"], "reason": "no price"})
        elif not row.get("quantity") or row["quantity"] <= 0:
            excluded.append({"symbol": row["symbol"], "reason": "nothing held"})
        else:
            names.append({"symbol": row["symbol"], "kind": row["kind"], "sector": row.get("sector"),
                          "quantity": float(row["quantity"]), "price": float(price),
                          "value": float(row["quantity"]) * float(price)})
    return names, excluded


def _sector(name: dict):
    return name["sector"] if name["kind"] == "STOCK" else None  # ETFs never count toward a sector cap


def target_weights(names: list[dict], targets: dict, total: float) -> dict[str, float]:
    symbols = {n["symbol"] for n in names}
    fixed = {s: pct / 100 for s, pct in (targets.get("overrides") or {}).items() if s in symbols}
    rest = max(0.0, 1 - sum(fixed.values()))
    free = [n for n in names if n["symbol"] not in fixed]
    if not free:
        return fixed

    if targets.get("rule") == "equal":
        return {**fixed, **{n["symbol"]: rest / len(free) for n in free}}

    start = {n["symbol"]: (n["value"] / total if n["value"] > 0 and total > 0 else rest / len(free)) for n in free}
    scale = rest / sum(start.values()) if sum(start.values()) > 0 else 0.0
    weights = {s: w * scale for s, w in start.items()}

    stock_cap = targets.get("max_stock_pct", 100) / 100
    sector_cap = targets.get("max_sector_pct", 100) / 100
    sector_of = {n["symbol"]: _sector(n) for n in names}
    clipped: set[str] = set()
    for _ in range(MAX_PASSES):
        freed = 0.0
        for symbol, weight in weights.items():
            if weight > stock_cap + EPS:
                freed += weight - stock_cap
                weights[symbol] = stock_cap
                clipped.add(symbol)
        by_sector = defaultdict(float)
        for symbol, weight in {**fixed, **weights}.items():
            if sector_of[symbol]:
                by_sector[sector_of[symbol]] += weight
        for sector, weight in by_sector.items():
            if weight <= sector_cap + EPS:
                continue
            members = [s for s in weights if sector_of[s] == sector]
            in_free = sum(weights[s] for s in members)
            room = max(0.0, sector_cap - (weight - in_free))
            factor = room / in_free if in_free > 0 else 0.0
            for s in members:
                freed += weights[s] * (1 - factor)
                weights[s] *= factor
                clipped.add(s)
        open_ = [s for s in weights if s not in clipped]
        if freed <= EPS or not open_:
            break  # weight nobody can absorb stays cash
        base = sum(weights[s] for s in open_)
        for s in open_:
            weights[s] += freed * (weights[s] / base if base > 0 else 1 / len(open_))
    return {**fixed, **weights}


def target_gaps(holdings: list[dict], targets: dict) -> tuple[dict[str, float], float, list[dict]]:
    """(target weight - current weight per symbol, total value, excluded), with
    no new money and no candidates -- the row actions on GET /portfolio."""
    names, excluded = universe(holdings)
    total = sum(n["value"] for n in names)
    weights = target_weights(names, targets, total)
    gaps = {n["symbol"]: weights.get(n["symbol"], 0.0) - (n["value"] / total if total else 0.0) for n in names}
    return gaps, total, excluded
