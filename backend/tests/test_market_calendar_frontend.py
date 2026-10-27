"""The frontend's NSE_HOLIDAYS (marketPhase) must match the backend calendar."""
import re
from datetime import date
from pathlib import Path

import pytest

from backend.core.market_calendar import HOLIDAYS

FORMATTERS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "formatters.js"


def test_frontend_holidays_match_backend():
    if not FORMATTERS.exists():
        pytest.skip("backend-only image: the frontend is not copied in")
    block = re.search(r"NSE_HOLIDAYS = new Set\(\[(.*?)\]\)", FORMATTERS.read_text(), re.S).group(1)
    assert {date.fromisoformat(d) for d in re.findall(r"'(\d{4}-\d{2}-\d{2})'", block)} == HOLIDAYS
