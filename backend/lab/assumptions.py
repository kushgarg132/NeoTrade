"""The one place execution assumptions live; every simulator reads them from here.

Charges are not duplicated: they come from engine/execution/costs.py.
"""

from dataclasses import dataclass
from typing import Literal

from backend.core.models import Side
from backend.engine.execution.costs import calculate_indian_costs


@dataclass(frozen=True)
class Execution:
    slippage_bps: float = 10.0  # adverse, per side (spread + impact)
    fill: Literal["next_open", "next_close"] = "next_open"


DEFAULT = Execution()                 # intraday/engine backtests, Picks study
DAILY = Execution(fill="next_close")  # factor portfolio (daily closes only)


def fill_price(price: float, side: Side, ex: Execution) -> float:
    sign = 1 if side == Side.BUY else -1
    return price * (1 + sign * ex.slippage_bps / 10_000)


def round_trip_return(entry: float, exit_: float, ex: Execution = DEFAULT,
                      notional: float = 1e5, product: str = "CNC") -> float:
    """Net return on `notional` of a long: slipped fills, real round-trip charges."""
    buy, sell = fill_price(entry, Side.BUY, ex), fill_price(exit_, Side.SELL, ex)
    qty = notional / buy
    charges = calculate_indian_costs(buy, qty, Side.BUY, product) + calculate_indian_costs(sell, qty, Side.SELL, product)
    return (qty * (sell - buy) - charges) / notional
