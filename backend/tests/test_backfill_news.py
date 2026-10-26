from datetime import date, datetime, timezone

import pandas as pd
import pytest

from backend.datalayer import backfill_news as bf
from backend.datalayer.news_sources import parse_rss
from backend.datalayer.outcomes import BENCH


def test_months_spans_year_end():
    assert bf.months("2024-11", "2025-01") == [
        (date(2024, 11, 1), date(2024, 12, 1)), (date(2024, 12, 1), date(2025, 1, 1)), (date(2025, 1, 1), date(2025, 2, 1))]


def test_parse_rss_keeps_old_items_only_when_asked():
    xml = b"""<rss><channel><item><title>Old story</title><link>u</link>
    <pubDate>Thu, 21 Mar 2024 07:00:00 GMT</pubDate></item></channel></rss>"""
    assert parse_rss(xml, "gnews_symbol", "COMPANY") == []
    assert [i["title"] for i in parse_rss(xml, "gnews_symbol", "COMPANY", max_age=None)] == ["Old story"]


def test_base_day_google_is_own_day_filing_before_close_is_day_before():
    noon = datetime(2024, 3, 21, 7, 0, tzinfo=timezone.utc)  # 12:30 IST
    assert bf.base_day({"published_at": noon, "feeds": ["gnews_symbol"]}) == date(2024, 3, 21)
    assert bf.base_day({"published_at": noon, "feeds": ["nse"]}) == date(2024, 3, 20)
    evening = datetime(2024, 3, 21, 12, 0, tzinfo=timezone.utc)  # 17:30 IST
    assert bf.base_day({"published_at": evening, "feeds": ["nse"]}) == date(2024, 3, 21)


def test_moves_counts_trading_days_after_the_base_close():
    days = pd.bdate_range("2024-03-18", periods=25)
    closes = {
        BENCH: pd.Series([100.0] * 25, index=days),
        "AAA": pd.Series([10.0] * 3 + [11.0] * 22, index=days),  # +10% on day 3 (Mar 21)
        "BBB": pd.Series([20.0] * 25, index=days),
    }
    # Base Mar 20 (day 2): the jump lands inside 1d.
    out = bf.moves(closes, days, "symbol", ["AAA"], ["BBB"], date(2024, 3, 20))
    assert out["move_1d"] == pytest.approx(0.10) and out["sector_move_5d"] == pytest.approx(0.10)
    assert out["move_20d"] == pytest.approx(0.10)
    # Base Mar 21 (the jump's own close): nothing left to count.
    assert bf.moves(closes, days, "symbol", ["AAA"], ["BBB"], date(2024, 3, 21))["move_5d"] == pytest.approx(0)
    # A weekend base uses Friday's close; no 20d bar yet near the end.
    late = bf.moves(closes, days, "market", [], [], date(2024, 4, 13))
    assert "move_1d" in late and "move_20d" not in late


def test_prune_compares_rewrites_within_a_day_only():
    def doc(title, day):
        return {"title": title, "scope": "MARKET", "symbols": [], "published_at": datetime(2024, 3, day, tzinfo=timezone.utc)}

    docs = [doc("Sensex jumps 800 points on bank rally", 4), doc("Sensex jumps 800 points on bank rally today", 4),
            doc("Sensex jumps 800 points on bank rally", 5)]
    assert [(d["published_at"].day, r) for d, r in bf.prune(docs)] == [(4, "duplicate")]
