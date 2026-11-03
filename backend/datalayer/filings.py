"""The filing lane: read NSE filings fast, score them from their own text and record what the
price then did. It places no orders and feeds nothing: `filing_scores` is read only by its report
(spec docs/superpowers/specs/2026-11-03-filing-lane-design.md).

The announcements feed returns 20 rows, or a whole day's with `from_date` and `to_date`. Filing
text is untrusted: it is fetched from one host, capped, parsed in memory, and treated as data.
"""

import asyncio
import hashlib
import logging
from urllib.parse import urlparse

import pypdfium2
import requests

from backend.datalayer import news_sources

logger = logging.getLogger(__name__)

PDF_HOST = "nsearchives.nseindia.com"
MAX_BYTES, MAX_PAGES, MAX_CHARS = 10 * 1024 * 1024, 6, 8000
MIN_TEXT = 100  # under this a PDF is a scan or empty: there is nothing to read
DOWNLOAD_SECONDS = 20


def filing_id(item: dict) -> str:
    key = f"{item['symbols'][0]}|{item['title']}|{item['published_at'].isoformat()}"
    return hashlib.sha1(key.encode()).hexdigest()


def allowed_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and parsed.hostname == PDF_HOST


def read_pdf(data: bytes) -> str:
    """The first pages' text, capped; "" for anything that will not parse."""
    try:
        document = pypdfium2.PdfDocument(data)
    except Exception:
        return ""
    try:
        parts = []
        for index in range(min(len(document), MAX_PAGES)):
            page = document[index]
            text_page = page.get_textpage()
            parts.append(text_page.get_text_range())
            text_page.close()
            page.close()
        return "\n".join(parts).strip()[:MAX_CHARS]
    except Exception as exc:
        logger.warning("filing pdf unreadable: %s", exc)
        return ""
    finally:
        document.close()


def _download(url: str) -> bytes | None:
    """The body, or None past the size cap."""
    response = requests.get(url, headers=news_sources.UA, timeout=DOWNLOAD_SECONDS, stream=True)
    try:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(64 * 1024):
            body += chunk
            if len(body) > MAX_BYTES:
                return None
        return bytes(body)
    finally:
        response.close()


async def fetch_text(url: str) -> tuple[str, bool]:
    """(text, pdf_ok). Never raises: a filing that cannot be read still gets scored on the feed's text."""
    if not allowed_url(url):
        return "", False
    try:
        data = await asyncio.to_thread(_download, url)
    except Exception as exc:
        logger.warning("filing pdf not fetched: %s", exc)
        return "", False
    if not data or not data.startswith(b"%PDF"):
        return "", False
    text = await asyncio.to_thread(read_pdf, data)
    return text, len(text) >= MIN_TEXT
