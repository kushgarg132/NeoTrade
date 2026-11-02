"""Which stocks make up an index: NSE's published lists, stored in factor/index_members/.
SENSEX has none: BSE's list is not reachable from here.

    ponytail: a snapshot, as factor/nifty200.csv is. NSE rebalances twice a year (March, September):
    re-download each ind_<file>list.csv from nsearchives.nseindia.com/content/indices/.
"""

import csv
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / "factor" / "index_members"
FILES = {
    "^NSEI": "nifty50", "^NSEBANK": "niftybank", "^NSMIDCP": "niftynext50", "^CNX100": "nifty100",
    "^CNX200": "nifty200", "^CRSLDX": "nifty500", "^NSEMDCP50": "niftymidcap50", "^CNXIT": "niftyit",
    "NIFTY_FIN_SERVICE.NS": "niftyfinance", "^CNXAUTO": "niftyauto", "^CNXPHARMA": "niftypharma",
    "^CNXFMCG": "niftyfmcg", "^CNXMETAL": "niftymetal", "^CNXREALTY": "niftyrealty",
    "^CNXENERGY": "niftyenergy", "^CNXINFRA": "niftyinfra", "^CNXPSUBANK": "niftypsubank",
}


@lru_cache(maxsize=None)
def members(ticker: str) -> tuple[dict, ...]:
    """Symbol, company name and NSE industry of each stock in the index; empty when no list is kept."""
    name = FILES.get(ticker)
    if name is None:
        return ()
    with (_DIR / f"{name}.csv").open() as f:
        return tuple({"symbol": r["Symbol"].strip(), "name": r["Company Name"].strip(), "sector": r["Industry"].strip()}
                     for r in csv.DictReader(f) if r.get("Series", "EQ").strip() == "EQ")
