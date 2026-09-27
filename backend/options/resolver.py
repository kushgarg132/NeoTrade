"""Which underlyings the options strategies may trade.

Expiry, strike and lot size are not decided here any more: they come from
the connected broker's own NFO instrument dump (InstrumentMaster.
option_contracts), and premiums from its live quotes (backend/options/
premiums.py). This file used to compute a "last Thursday of the month"
expiry and round strikes off a static interval table, both of which drift
from NSE's actual contract specs.
"""

# A small curated set of liquid NSE F&O large-caps.
FO_UNDERLYINGS: tuple[str, ...] = (
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "ITC", "LT", "AXISBANK", "KOTAKBANK",
)


def is_fo_eligible(symbol: str) -> bool:
    return symbol in FO_UNDERLYINGS
