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


MAX_CHARGE_PCT = 1.0  # a trade whose charges exceed this share of its value is not worth making
LONG_TERM_DAYS = 365
STCG_RATE, LTCG_RATE = 0.20, 0.125


def charges(side: str, quantity: float, price: float) -> float:
    from backend.core.models import Side
    from backend.engine.execution.costs import calculate_indian_costs

    return calculate_indian_costs(price, quantity, Side(side), "CNC")


def sell_tax(quantity: float, price: float, lots: list[tuple], today) -> dict:
    """Gain on selling `quantity` at `price`, oldest journal lot first, split
    short/long term. Quantity the journal cannot date is `unknown_qty`."""
    left, short_gain, long_gain = float(quantity), 0.0, 0.0
    for day, lot_qty, lot_price in lots:
        if left <= EPS:
            break
        take = min(left, lot_qty)
        gain = (price - lot_price) * take
        if (today - day).days > LONG_TERM_DAYS:
            long_gain += gain
        else:
            short_gain += gain
        left -= take
    unknown = max(0.0, left)
    est = None if unknown >= quantity - EPS else STCG_RATE * max(short_gain, 0) + LTCG_RATE * max(long_gain, 0)
    return {"short_gain": round(short_gain, 2), "long_gain": round(long_gain, 2),
            "unknown_qty": unknown, "est_tax": round(est, 2) if est is not None else None}


def plan_rebalance(holdings: list[dict], candidates: list[dict], targets: dict, new_money: float,
                   lots: dict, today) -> dict:
    names, excluded = universe(holdings)
    held = {n["symbol"] for n in names}
    for c in candidates:
        if c["symbol"] not in held and c.get("price") and c["price"] > 0:
            names.append({"symbol": c["symbol"], "kind": c.get("kind", "STOCK"), "sector": c.get("sector"),
                          "quantity": 0.0, "price": float(c["price"]), "value": 0.0})
    total = sum(n["value"] for n in names) + new_money
    weights = target_weights(names, targets, total) if total > 0 else {}
    skipped, sells, buys = [], [], []

    def row(n, side, quantity):
        value = quantity * n["price"]
        after = n["value"] + (value if side == "BUY" else -value)
        return {"symbol": n["symbol"], "side": side, "quantity": int(quantity), "price": n["price"], "value": round(value, 2),
                "charges": charges(side, quantity, n["price"]),
                "weight_now": n["value"] / total * 100, "weight_after": after / total * 100,
                "target_weight": weights.get(n["symbol"], 0.0) * 100, "tax": None}

    for n in names:
        delta = weights.get(n["symbol"], 0.0) * total - n["value"]
        if delta < 0:
            quantity = min(int(-delta // n["price"]), int(n["quantity"]))
            if quantity <= 0:
                continue
            trade = row(n, "SELL", quantity)
            if trade["charges"] > trade["value"] * MAX_CHARGE_PCT / 100:
                skipped.append({"symbol": n["symbol"], "reason": "charges above 1% of the trade"})
                continue
            trade["tax"] = sell_tax(quantity, n["price"], lots.get(n["symbol"], []), today)
            sells.append(trade)
        elif delta > 0:
            quantity = int(delta // n["price"])
            if quantity <= 0:
                skipped.append({"symbol": n["symbol"], "reason": "one share costs more than its slot"})
                continue
            buys.append((n, quantity))

    cash = new_money + sum(t["value"] - t["charges"] for t in sells)

    def cost(plan):
        return sum(q * n["price"] + charges("BUY", q, n["price"]) for n, q in plan if q > 0)

    wanted = cost(buys)
    if wanted > cash and wanted > 0:
        factor = max(cash, 0) / wanted
        buys = [(n, int(q * factor)) for n, q in buys]
        while buys and cost(buys) > cash:  # charges are not linear: trim the largest buy a share at a time
            i = max(range(len(buys)), key=lambda k: buys[k][1] * buys[k][0]["price"])
            if buys[i][1] <= 0:
                break
            buys[i] = (buys[i][0], buys[i][1] - 1)

    bought = []
    for n, quantity in buys:
        if quantity <= 0:
            continue  # scaled to nothing: the cash went to the others
        trade = row(n, "BUY", quantity)
        if trade["charges"] > trade["value"] * MAX_CHARGE_PCT / 100:
            skipped.append({"symbol": n["symbol"], "reason": "charges above 1% of the trade"})
            continue
        bought.append(trade)

    trades = sorted(sells, key=lambda t: -t["value"]) + sorted(bought, key=lambda t: -t["value"])
    spent = sum(t["value"] + t["charges"] for t in bought)
    return {"total": round(total, 2), "cash_left": round(cash - spent, 2), "trades": trades,
            "skipped": skipped, "excluded": excluded}


def suggest(row: dict, gap: float | None, total: float) -> dict | None:
    """The one-tap action for a holding row: a SELL verdict sells the whole
    holding, an ADD verdict buys up to its target. Broker cash is unknown, so
    a buy is not scaled to it; the broker refuses what cannot be paid for."""
    price = row.get("last_price") or row.get("close_price")
    if row.get("kind") not in TRADABLE or not price or price <= 0:
        return None
    if row.get("verdict") == "SELL":
        side, quantity = "SELL", int(row.get("quantity") or 0)
    elif row.get("verdict") == "ADD":
        side, quantity = "BUY", int((gap or 0.0) * total // price)
        if quantity <= 0:
            return {"at_target": True}
    else:
        return None
    if quantity <= 0:
        return None
    if charges(side, quantity, price) > quantity * price * MAX_CHARGE_PCT / 100:
        return {"skipped": "charges above 1% of the trade"}
    return {"side": side, "quantity": quantity, "price": float(price)}
