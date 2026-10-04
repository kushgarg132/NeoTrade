"""Every autopilot order passes this or is refused. Pure, no I/O.

Entries (buys) must respect every limit; an exit (selling a symbol the
autopilot holds) only needs the switch on and the market open -- getting
out is never blocked by a cap. Short selling is not allowed."""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from backend.core.models import Side

PRODUCTS = {"CNC", "MIS"}


@dataclass
class FenceState:
    deployed: float                # rupees in open autopilot positions, at mark
    entries_today: int
    open_symbols: set = field(default_factory=set)
    kill_tripped: bool = False
    session_ok: bool = True


@lru_cache(maxsize=1)
def universe() -> frozenset:
    from backend.factor.data import universe as nifty200
    return frozenset(nifty200())


def check(order, price: float, state: FenceState, prefs: dict) -> Optional[str]:
    """None if the order may go, else why not (shown to the user)."""
    if not prefs.get("autopilot_enabled"):
        return "The autopilot is off."
    if not state.session_ok:
        return "The market is closed."
    if order.product not in PRODUCTS:
        return "The autopilot trades NSE equity only (CNC or MIS)."
    if order.side == Side.SELL:
        return None if order.symbol in state.open_symbols else "The autopilot does not short sell."
    notional = price * order.quantity
    if state.kill_tripped:
        return "The daily loss limit was hit: no new entries today."
    if order.symbol not in universe():
        return f"{order.symbol} is outside the autopilot's universe (Nifty 200)."
    if order.symbol in state.open_symbols:
        return f"The autopilot is already holding {order.symbol}."
    if notional > prefs["autopilot_per_trade_cap"] + 1e-6:
        return f"₹{notional:,.0f} is over the per-trade cap of ₹{prefs['autopilot_per_trade_cap']:,.0f}."
    if state.deployed + notional > prefs["autopilot_capital"] + 1e-6:
        return (f"₹{notional:,.0f} more would exceed the autopilot capital of ₹{prefs['autopilot_capital']:,.0f} "
                f"(₹{state.deployed:,.0f} deployed).")
    if state.entries_today >= prefs["autopilot_max_trades_per_day"]:
        return f"Already {state.entries_today} trades today (limit {prefs['autopilot_max_trades_per_day']})."
    return None
