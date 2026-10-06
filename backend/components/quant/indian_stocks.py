"""
List of Indian Small Cap and Mid Cap stocks for scanning.
These stocks tend to show more movement than large caps.
"""

# Nifty Midcap 50 sample stocks.
# 2026-10-05: dropped delisted/renamed names and anything under Rs 50 (wide spreads).
MIDCAP_STOCKS = [
    "ASTRAL", "BALKRISIND", "BATAINDIA", "BHEL", "BIOCON",
    "CANFINHOME", "COFORGE", "COLPAL", "CONCOR", "CUMMINSIND",
    "DALBHARAT", "ESCORTS", "FEDERALBNK", "FORTIS", "GMRAIRPORT",
    "HINDPETRO", "IDFCFIRSTB", "INDHOTEL", "INDUSTOWER",
    "IRCTC", "JINDALSTEL", "JUBLFOOD", "LICHSGFIN", "LUPIN",
    "MFSL", "MPHASIS", "NATIONALUM", "NMDC", "OBEROIRLTY",
    "PAGEIND", "PETRONET", "PFC", "PIIND", "POLYCAB",
    "RAMCOCEM", "RECLTD", "SAIL", "TATACOMM", "TATAPOWER",
    "VOLTAS", "ZEEL"
]

# Small cap stocks with high volatility
SMALLCAP_STOCKS = [
    "ADANIPOWER", "APOLLOTYRE", "ASHOKLEY", "AUROPHARMA",
    "BALRAMCHIN", "BSOFT", "CANBK", "CHAMBLFERT",
    "COCHINSHIP", "DEEPAKNTR", "DELTACORP", "EIDPARRY",
    "EXIDEIND", "GAIL", "GLENMARK", "GNFC", "GRANULES",
    "HFCL", "HINDZINC", "IDBI", "IEX",
    "NHPC", "NLCINDIA", "ORIENTELEC", "PNBHOUSING", "RBLBANK",
    "RELAXO", "RVNL", "SJVN", "TATAELXSI",
    "THERMAX", "TIINDIA", "TRENT", "ZYDUSLIFE"
]

# Combined list for scanning - focus on mid and small caps
ALL_SCAN_STOCKS = MIDCAP_STOCKS + SMALLCAP_STOCKS

# Top picks for quick testing (10 stocks with typically high movement)
HIGH_VOLATILITY_PICKS = [
    "SUZLON",      # Renewable energy - high volatility
    "ADANIPOWER",  # Power sector
    "IRCTC",       # Travel/Railways
    "TATAPOWER",   # Power sector
    "SAIL",        # Steel - commodity linked
    "JINDALSTEL",  # Steel
    "NHPC",        # Hydro power
    "HFCL",        # Telecom infra
    "RVNL",        # Railways
    "IEX",         # Power exchange
]

def get_stock_symbol_nse(symbol: str) -> str:
    """Convert to yfinance NSE format"""
    return f"{symbol}.NS"
