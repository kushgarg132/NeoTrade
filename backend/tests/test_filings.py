"""The filing lane: read NSE filings, score them, record what the price did. No trading path."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.datalayer import filings

AT = datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)  # 10:30 AM IST, a Tuesday
ITEM = {"symbols": ["TCS"], "title": "TCS: Order", "published_at": AT}


def _pdf(text: str = "") -> bytes:
    """A minimal one-page PDF with `text` drawn in Helvetica."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            b"<</Length %d>>stream\n%s\nendstream" % (len(stream), stream),
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    start = len(out)
    out += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % start


def test_only_nse_archive_over_https_is_allowed():
    assert filings.allowed_url("https://nsearchives.nseindia.com/corporate/X.pdf")
    for bad in ("http://nsearchives.nseindia.com/x.pdf", "https://evil.com/x.pdf",
                "https://nsearchives.nseindia.com.evil.com/x.pdf", "", "file:///etc/passwd"):
        assert not filings.allowed_url(bad)


def test_id_is_stable_and_changes_with_the_filing():
    assert filings.filing_id(ITEM) == filings.filing_id(dict(ITEM))
    assert filings.filing_id(ITEM) != filings.filing_id({**ITEM, "title": "TCS: Order (Revised)"})


def test_read_pdf_returns_the_text_and_caps_it():
    assert "Order worth 500 crore" in filings.read_pdf(_pdf("Order worth 500 crore"))
    assert len(filings.read_pdf(_pdf("x" * 200))) <= filings.MAX_CHARS


def test_garbage_bytes_do_not_raise():
    assert filings.read_pdf(b"not a pdf") == ""


class _Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("refused")

    def close(self):
        pass


URL = "https://nsearchives.nseindia.com/corporate/X.pdf"


def _serve(monkeypatch, body, status=200):
    calls = []

    def get(url, **kw):
        calls.append(url)
        return _Response(body, status)

    monkeypatch.setattr(filings.requests, "get", get)
    return calls


async def test_a_readable_pdf_is_ok(monkeypatch):
    _serve(monkeypatch, _pdf("Order worth 500 crore from a large customer. " * 3))
    text, ok = await filings.fetch_text(URL)
    assert ok and "500 crore" in text


async def test_a_disallowed_host_makes_no_request(monkeypatch):
    calls = _serve(monkeypatch, _pdf("x"))
    assert await filings.fetch_text("https://evil.com/x.pdf") == ("", False)
    assert calls == []


async def test_an_oversized_download_is_not_read(monkeypatch):
    _serve(monkeypatch, b"%PDF" + b"0" * (filings.MAX_BYTES + 1))
    assert await filings.fetch_text(URL) == ("", False)


async def test_a_refused_download_is_not_ok(monkeypatch):
    _serve(monkeypatch, b"", status=403)
    assert await filings.fetch_text(URL) == ("", False)


async def test_a_scanned_pdf_with_no_text_is_not_ok(monkeypatch):  # Review Focus 1
    _serve(monkeypatch, _pdf(""))
    assert (await filings.fetch_text(URL))[1] is False
