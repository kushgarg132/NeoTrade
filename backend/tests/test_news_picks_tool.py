from datetime import datetime, timezone

import pandas as pd
import pytest

from backend.forecast.research import news_picks_tool as nv


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


def _series(rows):
    rows = sorted(rows)
    return ([pd.Timestamp(d) for d, _, _ in rows], [x for _, x, _ in rows], [i for _, _, i in rows])


def test_window_mean_is_impact_weighted_over_the_look_back():
    s = _series([("2025-03-01", -1.0, 9), ("2025-03-04", 1.0, 3), ("2025-03-05", 0.5, 6)])
    # (Mar 1, Mar 5]: the Mar 1 item is out.
    assert nv.window_mean(s, pd.Timestamp("2025-03-05"), 4) == pytest.approx((1.0 * 3 + 0.5 * 6) / 9)
    assert nv.window_mean(s, pd.Timestamp("2025-02-20"), 5) is None
    assert nv.window_mean(None, pd.Timestamp("2025-03-05"), 5) is None


def _events(rows):
    return pd.DataFrame(rows, columns=["symbol", "signal", "net", "nifty"]).assign(
        signal=lambda f: pd.to_datetime(f["signal"]))


def test_tilt_ic_positive_when_better_sector_news_means_better_returns():
    sector_of = {f"S{i}": f"Sec{i}" for i in range(6)}
    sectors = {f"Sec{i}": _series([("2025-03-01", -1 + i * 0.4, 5), ("2026-03-01", -1 + i * 0.4, 5)]) for i in range(6)}
    rows = [(f"S{i}", f"{y}-03-03", 0.01 * i, 0.0) for y in (2025, 2026) for i in range(6)]
    out = nv.tilt(_events(rows), sectors, sector_of, [2025, 2026])
    assert out["months"] == 2 and out["mean_ic"] == pytest.approx(1.0) and out["passes"] is True
    flipped = [(s, d, -n, b) for s, d, n, b in rows]
    assert nv.tilt(_events(flipped), sectors, sector_of, [2025, 2026])["passes"] is False
    # Signals outside the test years count for nothing.
    assert nv.tilt(_events(rows), sectors, sector_of, [2024])["passes"] is None


def test_regime_passes_when_risk_off_baskets_lose():
    market = _series([(f"2025-{m:02d}-01", -0.8 if m <= 3 else 0.6, 5) for m in range(1, 7)])
    rows = [(f"S{i}", f"2025-{m:02d}-02", (-0.03 if m <= 3 else 0.02), 0.0) for m in range(1, 7) for i in range(3)]
    base = pd.Series(0.0, index=pd.period_range("2025-01", "2025-06", freq="M"))
    out = nv.regime(_events(rows), market, base, [2025])
    assert out["buckets"]["risk_off"]["months"] == 3 and out["buckets"]["risk_on"]["months"] == 3
    assert out["passes"] is True
    winners = [(s, d, -n, b) for s, d, n, b in rows]
    assert nv.regime(_events(winners), market, base, [2025])["passes"] is False
