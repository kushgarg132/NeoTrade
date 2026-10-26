from datetime import datetime, timezone

import pandas as pd

from backend.forecast.research import news_veto_tool as nv


def _item(day, impacts=(), title="", feeds=("gnews_symbol",), symbols=()):
    return {"published_at": datetime(2025, 3, day, 6, 0, tzinfo=timezone.utc), "impacts": list(impacts),
            "title": title, "feeds": list(feeds), "symbols": list(symbols)}


def test_flags_keep_only_strong_negative_symbol_news_and_nse_results_filings():
    items = [
        _item(3, [{"type": "symbol", "target": "TCS", "direction": -0.8, "impact": 8}]),
        _item(4, [{"type": "symbol", "target": "TCS", "direction": -0.8, "impact": 5}]),  # too weak
        _item(5, [{"type": "sector", "target": "IT", "direction": -0.9, "impact": 9}]),  # not a symbol
        _item(6, title="TCS: Financial Results for Q4", feeds=("nse",), symbols=("TCS",)),
        _item(7, title="TCS financial results beat", symbols=("TCS",)),  # Google, not a filing
    ]
    bad, results = nv.flags(items)
    assert bad == {"TCS": [pd.Timestamp("2025-03-03")]}
    assert results == {"TCS": [pd.Timestamp("2025-03-06")]}


def test_tag_windows():
    ev = pd.DataFrame({"symbol": ["TCS", "TCS", "INFY"],
                       "signal": pd.to_datetime(["2025-03-05", "2025-03-07", "2025-03-05"]),
                       "exit": pd.to_datetime(["2025-03-20", "2025-03-20", "2025-03-06"])})
    bad = {"TCS": [pd.Timestamp("2025-03-03")]}
    results = {"TCS": [pd.Timestamp("2025-03-10")], "INFY": [pd.Timestamp("2025-03-05")]}
    out = nv.tag(ev, bad, results)
    # Bad news 2 days before the first signal (inside 3 days), 4 days before the second (outside).
    assert out["bad_news"].tolist() == [True, False, False]
    # Results inside (signal, exit]; INFY's are on the signal day itself, already in the price.
    assert out["results"].tolist() == [True, True, False]


def test_verdict_needs_enough_vetoed_and_a_better_kept_set(monkeypatch):
    def fake_edge(ev, baseline, wf):  # excess = mean of column x, t grows with it
        m = float(ev["x"].mean())
        return {"oos_n": len(ev), "excess": m, "t": m * 100, "edge": False}

    monkeypatch.setattr(nv.study, "adjusted_edge", fake_edge)
    # Vetoed events lose (x = -0.02), the rest gain: dropping them helps.
    ev = pd.DataFrame({"bad_news": [True] * 25 + [False] * 75, "x": [-0.02] * 25 + [0.01] * 75})
    assert nv.verdict(ev, "bad_news", None, {})["passes"] is True
    assert nv.verdict(ev.iloc[5:], "bad_news", None, {})["passes"] is True  # 20 vetoed is the floor
    assert nv.verdict(ev.iloc[6:], "bad_news", None, {})["passes"] is None
    # Vetoed events were the winners: dropping them hurts.
    assert nv.verdict(ev.assign(x=-ev["x"]), "bad_news", None, {})["passes"] is False
