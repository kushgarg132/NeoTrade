"""NseEquityListSource / BseEquityListSource: mapping from each exchange's
public equity-list response shape into Instrument, plus the synthetic
instrument_token scheme that stands in for Kite's real (unavailable without
a paid session) numeric ids."""

import httpx

from backend.instruments.free_source import (
    NSE_ETF_CSV_URL,
    BseEquityListSource,
    NseEquityListSource,
    _synthetic_token,
)


class _FakeResponse:
    def __init__(self, text=None, json_data=None):
        self.text = text
        self._json = json_data

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


_NSE_CSV = (
    "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
    "RELIANCE,Reliance Industries Limited,EQ,01-JAN-1995,10,1,INE002A01018,10\n"
    ",Some Blank Row,EQ,01-JAN-1995,10,1,,10\n"
)


async def test_nse_source_maps_rows_and_skips_blank_symbols(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return _FakeResponse(text=_NSE_CSV)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    instruments = await NseEquityListSource().fetch()

    assert len(instruments) == 1
    inst = instruments[0]
    assert inst.exchange == "NSE"
    assert inst.tradingsymbol == "RELIANCE"
    assert inst.name == "Reliance Industries Limited"
    assert inst.isin == "INE002A01018"
    assert inst.instrument_token == _synthetic_token("NSE", "RELIANCE")


_NSE_ETF_CSV = (
    "Symbol,Underlying Asset,SecurityName,DateofListing,MarketLot,ISINNumber,FaceValue,ETF Underlying,Underlying Key\n"
    "SILVERBEES,Silver,NIPINDETFSILVERBEES,01-Feb-22,1,INF204KC1402,1,COMMODITY,Silver\n"
)


async def test_nse_source_also_parses_etf_list_headers(monkeypatch):
    async def fake_get(self, url, **kwargs):
        assert url == NSE_ETF_CSV_URL
        return _FakeResponse(text=_NSE_ETF_CSV)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    [inst] = await NseEquityListSource(NSE_ETF_CSV_URL).fetch()

    assert (inst.exchange, inst.tradingsymbol) == ("NSE", "SILVERBEES")
    assert inst.name == "NIPINDETFSILVERBEES"
    assert inst.isin == "INF204KC1402"


_BSE_JSON = [
    {
        "SCRIP_CD": "539594", "Scrip_Name": "Mishtann Foods Ltd",
        "scrip_id": "MISHTANN", "ISIN_NUMBER": "INE094S01041",
    },
    {"SCRIP_CD": "999999", "Scrip_Name": "No Scrip Id", "scrip_id": "", "ISIN_NUMBER": None},
]


async def test_bse_source_maps_rows_and_skips_blank_scrip_ids(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return _FakeResponse(json_data=_BSE_JSON)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    instruments = await BseEquityListSource().fetch()

    assert len(instruments) == 1
    inst = instruments[0]
    assert inst.exchange == "BSE"
    assert inst.tradingsymbol == "MISHTANN"
    assert inst.name == "Mishtann Foods Ltd"
    assert inst.isin == "INE094S01041"


def test_synthetic_tokens_are_stable_and_distinguish_exchange():
    assert _synthetic_token("NSE", "RELIANCE") == _synthetic_token("NSE", "RELIANCE")
    assert _synthetic_token("NSE", "RELIANCE") != _synthetic_token("BSE", "RELIANCE")
    # Clear of any realistic real Kite instrument_token.
    assert _synthetic_token("NSE", "RELIANCE") > 1_000_000_000
