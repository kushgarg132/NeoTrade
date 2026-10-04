"""Mirrors held up to the trader's own journal: what charges took from
their P&L, how often they trade, and how they did against simply holding
the Nifty. Pure, no I/O.

Broker trade books carry no charges and no product, so charges are an
estimate from the same Indian cost model the engine uses
(engine/execution/costs.py): a stock round trip opened and closed the same
IST day is intraday, anything else delivery; CE/PE use the options model.
ponytail: futures are costed at intraday equity rates; add a futures model
if futures traders show up.
"""

from datetime import date
from typing import Optional

from backend.core.models import Side
from backend.engine.execution.costs import calculate_indian_costs
from backend.engine.execution.options_costs import calculate_options_costs
from backend.engine.session import IST

# SEBI FY23 study: 80% of intraday traders with more than 500 trades a year lost money.
SEBI_HEAVY_TRADER = 500
MIN_SPAN_DAYS = 30  # don't annualise a week of activity into a yearly rate


def _product(trip: dict) -> str:
    if trip["kind"] in ("CALL", "PUT"):
        return "options"
    closed = trip.get("closed_at")
    same_day = closed is not None and closed.astimezone(IST).date() == trip["opened_at"].astimezone(IST).date()
    return "intraday" if same_day or trip["kind"] == "FUTURE" else "delivery"


def _charge(fill: dict, product: str) -> float:
    side = Side.BUY if str(fill["side"]).upper() == "BUY" else Side.SELL
    price, qty = float(fill["price"]), float(fill["quantity"])
    if product == "options":
        return calculate_options_costs(price, qty, side)
    return calculate_indian_costs(price, qty, side, "MIS" if product == "intraday" else "CNC")


def costs(trades: list[dict], trips: list[dict], capital: float) -> dict:
    product_of = {tid: _product(trip) for trip in trips for tid in trip["trade_ids"]}
    by_kind: dict[str, float] = {}
    for fill in trades:
        product = product_of.get(fill["_id"], "delivery")
        by_kind[product] = round(by_kind.get(product, 0.0) + _charge(fill, product), 2)
    charges = round(sum(by_kind.values()), 2)
    gross = round(sum(t["pnl"] for t in trips if t.get("pnl") is not None), 2)
    times = [f["traded_at"] for f in trades]
    span = max((max(times) - min(times)).days, MIN_SPAN_DAYS) if times else MIN_SPAN_DAYS
    per_year = len(trades) * 365 / span if trades else 0.0
    return {
        "fills": len(trades),
        "turnover": round(sum(float(f["price"]) * float(f["quantity"]) for f in trades), 2),
        "charges": charges,
        "charges_by_kind": by_kind,
        "gross_pnl": gross,
        "net_pnl": round(gross - charges, 2),
        "charges_pct_of_capital": charges / capital if capital else None,
        "trades_per_year": round(per_year),
        "heavy_trader": per_year > SEBI_HEAVY_TRADER,
    }


def benchmark(net_pnl: float, capital: float, start: date, end: date, nifty: list) -> Optional[dict]:
    """The trader's net P&L as a return on capital vs the Nifty over the same
    days. `nifty` is [(date, close)] oldest first; None without coverage."""
    window = [close for day, close in nifty if start <= day <= end]
    if len(window) < 2 or not capital:
        return None
    yours = net_pnl / capital
    index = window[-1] / window[0] - 1
    return {"start": start.isoformat(), "end": end.isoformat(), "your_return": yours,
            "nifty_return": index, "difference": yours - index}


def text(m: dict, b: Optional[dict]) -> str:
    """The weekly Telegram note."""
    lines = [f"Your trading so far: P&L ₹{m['gross_pnl']:+,.0f} before charges, "
             f"₹{m['net_pnl']:+,.0f} after ~₹{m['charges']:,.0f} of charges."]
    if m["heavy_trader"]:
        lines.append(f"You're on pace for ~{m['trades_per_year']:,} trades a year. SEBI found 80% of "
                     f"intraday traders above {SEBI_HEAVY_TRADER} a year lost money.")
    if b:
        lines.append(f"Return on capital {b['your_return']:+.1%} vs Nifty {b['nifty_return']:+.1%} "
                     f"since {b['start']}.")
    return "\n".join(lines)
