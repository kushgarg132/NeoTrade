"""Shared helper for the adapters' get_holdings."""

# ponytail: NSE ETFs by their naming convention (NIFTYBEES, GOLDBEES,
# MON100, ...ETF). An ETF that follows neither shows as a stock; a real
# classification needs the exchange's ETF list.
_ETF_MARKERS = ("BEES", "ETF", "IETF")


def kind_of(symbol: str) -> str:
    plain = symbol.upper().removesuffix("-EQ")
    return "ETF" if any(marker in plain for marker in _ETF_MARKERS) else "STOCK"
