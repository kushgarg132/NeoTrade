"""backend.research.flags.stock_flags: plain-fact chips over a stock snapshot."""

from backend.research.flags import stock_flags


def _flag(flags, code):
    return next((f for f in flags if f["code"] == code), None)


def _one(code, technicals=None, company=None):
    found = _flag(stock_flags(technicals or {}, company or {}), code)
    return (found["label"], found["tone"]) if found else None


def test_trend():
    assert _one("trend", {"trend": "up"}) == ("Uptrend", "up")
    assert _one("trend", {"trend": "down"}) == ("Downtrend", "down")
    assert _one("trend", {"trend": "choppy"}) == ("Sideways", "neutral")


def test_vs_200():
    assert _one("vs_200", {"price": 110, "sma_200": 100}) == ("Above 200-day avg", "up")
    assert _one("vs_200", {"price": 90, "sma_200": 100}) == ("Below 200-day avg", "down")


def test_cross():
    assert _one("cross", {"sma_50": 110, "sma_200": 100}) == ("Golden cross", "up")
    assert _one("cross", {"sma_50": 90, "sma_200": 100}) == ("Death cross", "down")


def test_rsi():
    assert _one("rsi", {"rsi": 70.1}) == ("RSI 70 · overbought", "down")
    assert _one("rsi", {"rsi": 69.9}) is None
    assert _one("rsi", {"rsi": 25.6}) == ("RSI 26 · oversold", "up")


def test_near_high_and_low():
    assert _one("near_high", {"price": 95, "high_52w": 100}) == ("Near 52-week high", "neutral")
    assert _one("near_high", {"price": 94.9, "high_52w": 100}) is None
    assert _one("near_low", {"price": 105, "low_52w": 100}) == ("Near 52-week low", "neutral")
    assert _one("near_low", {"price": 105.1, "low_52w": 100}) is None


def test_company_52_week_figures_win_over_history():
    assert _one("near_high", {"price": 95, "high_52w": 200}, {"week_52_high": 100}) is not None
    assert _one("near_high", {"price": 95, "high_52w": 100}, {"week_52_high": None}) is not None


def test_volume():
    assert _one("volume", {"volume_ratio": 1.5}) == ("Volume 1.5× avg", "neutral")
    assert _one("volume", {"volume_ratio": 2.34}) == ("Volume 2.3× avg", "neutral")
    assert _one("volume", {"volume_ratio": 1.49}) is None


def test_cash():
    assert _one("cash", company={"total_debt": 10, "total_cash": 5}) == ("Debt > cash", "down")
    assert _one("cash", company={"total_debt": 5, "total_cash": 10}) == ("Net cash", "up")


def test_loss_and_dividend():
    assert _one("loss", company={"trailing_eps": -1}) == ("Loss-making", "down")
    assert _one("loss", company={"trailing_eps": 3}) is None
    assert _one("dividend", company={"dividend_yield": 0.021}) == ("Dividend 2.1%", "neutral")
    assert _one("dividend", company={"dividend_yield": 0}) is None


def test_empty_inputs():
    assert stock_flags({}, {}) == []


def test_company_all_none():
    company = {k: None for k in ("week_52_high", "week_52_low", "total_debt", "total_cash", "trailing_eps", "dividend_yield")}
    assert [f["code"] for f in stock_flags({"trend": "up"}, company)] == ["trend"]


def test_order_follows_the_table():
    flags = stock_flags(
        {"trend": "up", "price": 110, "sma_50": 105, "sma_200": 100, "rsi": 75, "volume_ratio": 2},
        {"trailing_eps": -1},
    )
    assert [f["code"] for f in flags] == ["trend", "vs_200", "cross", "rsi", "volume", "loss"]


def test_equal_averages_raise_no_cross_or_side():
    flags = stock_flags({"price": 100, "sma_50": 100, "sma_200": 100}, {})
    assert _flag(flags, "cross") is None
    assert _flag(flags, "vs_200") is None
