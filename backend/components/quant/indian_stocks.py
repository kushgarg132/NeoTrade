"""
List of Indian Small Cap and Mid Cap stocks for scanning.
These stocks tend to show more movement than large caps.
"""

# Nifty Midcap 50 sample stocks
MIDCAP_STOCKS = [
    "ASTRAL", "BALKRISIND", "BATAINDIA", "BHEL", "BIOCON",
    "CANFINHOME", "COFORGE", "COLPAL", "CONCOR", "CUMMINSIND",
    "DALBHARAT", "ESCORTS", "FEDERALBNK", "FORTIS", "GMRAIRPORT",
    "GUJGASLTD", "HINDPETRO", "IDFCFIRSTB", "INDHOTEL", "INDUSTOWER",
    "IRCTC", "JINDALSTEL", "JUBLFOOD", "LICHSGFIN", "LUPIN",
    "MFSL", "MPHASIS", "NATIONALUM", "NMDC", "OBEROIRLTY",
    "PAGEIND", "PETRONET", "PFC", "PIIND", "POLYCAB",
    "RAMCOCEM", "RECLTD", "SAIL", "TATACOMM", "TATAPOWER",
    "TRIDENT", "VOLTAS", "ZEEL"
]

# Small cap stocks with high volatility
SMALLCAP_STOCKS = [
    "ADANIPOWER", "ALOKINDS", "APOLLOTYRE", "ASHOKLEY", "AUROPHARMA",
    "BALRAMCHIN", "BSOFT", "CANBK", "CENTRALBK", "CHAMBLFERT",
    "COCHINSHIP", "DEEPAKNTR", "DELTACORP", "DISHTV", "EIDPARRY",
    "EXIDEIND", "GAIL", "GLENMARK", "GNFC", "GRANULES",
    "GSPL", "HFCL", "HINDZINC", "IDBI", "IEX",
    "NHPC", "NLCINDIA", "ORIENTELEC", "PNBHOUSING", "RBLBANK",
    "RELAXO", "RVNL", "SJVN", "SUZLON", "TATAELXSI",
    "TATAMTRDVR", "THERMAX", "TIINDIA", "TRENT", "ZYDUSLIFE"
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

def get_all_symbols_for_scan() -> list:
    """Get all symbols in yfinance format"""
    return [get_stock_symbol_nse(s) for s in HIGH_VOLATILITY_PICKS]

def get_full_scan_list() -> list:
    """Get full list of mid/small cap symbols"""
    return [get_stock_symbol_nse(s) for s in ALL_SCAN_STOCKS]
