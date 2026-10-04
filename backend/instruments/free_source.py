"""InstrumentSource implementations backed by NSE's and BSE's own public
equity-list downloads -- a free stopgap for the real instrument universe
while this deployment has no paid, connected Kite Connect session (see
kite_source.py). Both are the same CSV/JSON endpoints those exchanges' own
websites call, not an officially documented third-party API: no key or
login is needed, but they're not a stable contract either -- expect them to
need re-checking if NSE/BSE ever change the response shape or start
blocking non-browser User-Agents.

Neither exchange publishes the internal numeric instrument_token/
exchange_token pair Kite's own dump uses for live tick subscriptions
(KiteTicker, backend/routers/trading.py) -- those are Kite-internal ids
with no public equivalent. This synthesizes stable, collision-resistant
tokens instead (a large-offset hash of exchange+tradingsymbol), which is
fine for search/resolution/analysis (yfinance-backed, keyed on
tradingsymbol+exchange, never touches instrument_token) but NOT sufficient
for live paper-trading ticks. A real Kite sync later overwrites these rows
in place (InstrumentMaster.upsert_many matches on (exchange, tradingsymbol))
once a session is connected, so nothing needs to be undone when that happens.
"""

import csv
import io
import logging
import zlib

import httpx

from backend.instruments.models import Instrument

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}

NSE_EQUITY_CSV_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
# EQUITY_L.csv omits ETFs (SILVERBEES, LIQUIDBEES, ...); NSE lists them separately.
NSE_ETF_CSV_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
BSE_EQUITY_LIST_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)

# Real Kite NSE/BSE equity instrument_tokens observed in the wild stay well
# under this. Offsetting synthetic ones here keeps them from ever colliding
# with a real Kite sync's row for a *different* symbol.
_SYNTHETIC_TOKEN_OFFSET = 2_000_000_000


def _synthetic_token(exchange: str, tradingsymbol: str) -> int:
    return _SYNTHETIC_TOKEN_OFFSET + zlib.crc32(f"{exchange}:{tradingsymbol}".encode())


class NseEquityListSource:
    """NSE's own bundled full equity list (SYMBOL, NAME, ISIN, ...) -- a
    public CSV NSE's own website downloads, no API key or login required.
    Also parses NSE's ETF list (NSE_ETF_CSV_URL), which names the same
    columns Symbol / SecurityName / ISINNumber."""

    def __init__(self, url: str = NSE_EQUITY_CSV_URL):
        self.url = url

    async def fetch(self) -> list[Instrument]:
        async with httpx.AsyncClient(timeout=30.0, headers=_BROWSER_HEADERS) as client:
            resp = await client.get(self.url)
            resp.raise_for_status()

        # NSE's own CSV has a leading space on every header after the first
        # ("SYMBOL,NAME OF COMPANY, SERIES, ... ISIN NUMBER, ...") -- strip
        # keys so lookups below don't have to know that.
        instruments = []
        for raw_row in csv.DictReader(io.StringIO(resp.text)):
            row = {(key or "").strip(): value for key, value in raw_row.items()}
            symbol = (row.get("SYMBOL") or row.get("Symbol") or "").strip()
            if not symbol:
                continue
            instruments.append(Instrument(
                exchange="NSE",
                tradingsymbol=symbol,
                name=(row.get("NAME OF COMPANY") or row.get("SecurityName") or symbol).strip(),
                instrument_token=_synthetic_token("NSE", symbol),
                exchange_token=_synthetic_token("NSE", symbol),
                instrument_type="EQ",
                segment="NSE",
                lot_size=1,
                tick_size=0.05,
                isin=(row.get("ISIN NUMBER") or row.get("ISINNumber") or "").strip() or None,
            ))
        return instruments


class BseEquityListSource:
    """BSE's own scrip master -- the public JSON endpoint bseindia.com's own
    "List of Scrips" page calls, no API key or login required."""

    def __init__(self, url: str = BSE_EQUITY_LIST_URL):
        self.url = url

    async def fetch(self) -> list[Instrument]:
        headers = {**_BROWSER_HEADERS, "Referer": "https://www.bseindia.com/corporates/List_Scrips.aspx"}
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            resp = await client.get(self.url)
            resp.raise_for_status()

        instruments = []
        for row in resp.json():
            symbol = (row.get("scrip_id") or "").strip()
            if not symbol:
                continue
            instruments.append(Instrument(
                exchange="BSE",
                tradingsymbol=symbol,
                name=(row.get("Scrip_Name") or symbol).strip(),
                instrument_token=_synthetic_token("BSE", symbol),
                exchange_token=_synthetic_token("BSE", symbol),
                instrument_type="EQ",
                segment="BSE",
                lot_size=1,
                tick_size=0.01,
                isin=(row.get("ISIN_NUMBER") or "").strip() or None,
            ))
        return instruments
