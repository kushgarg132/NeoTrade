import pandas as pd
import pytest

from backend.strategies.indicators import Indicators


@pytest.fixture
def closes():
    # Wilder's own worked RSI example (New Concepts in Technical Trading Systems).
    return pd.Series([
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
        45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
    ])


def _wilder_rsi_reference(series: pd.Series, period: int = 14) -> pd.Series:
    """Textbook longhand Wilder RSI: SMA seed over the first `period` changes,
    then Wilder smoothing. Used to check the vectorised implementation."""
    delta = series.diff().dropna()
    gains = delta.clip(lower=0.0).tolist()
    losses = (-delta.clip(upper=0.0)).tolist()

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out = [float("nan")] * (len(series))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss:
            out[i + 1] = 100 - (100 / (1 + avg_gain / avg_loss))
    return pd.Series(out, index=series.index)


def test_rsi_matches_wilder_reference():
    """Our `ewm`-based RSI seeds from bar zero, the textbook seeds from an SMA of
    the first 14 changes. That difference decays as (13/14)^n, so on a long
    series the two must converge — which is what makes the vectorised form a
    legitimate Wilder RSI rather than a different indicator.
    """
    n = 300
    # Deterministic, non-monotonic series so gains and losses both accumulate.
    values = [100.0]
    for i in range(1, n):
        values.append(values[-1] + (3.0 if i % 3 else -4.0) * (1 + (i % 7) / 10))
    series = pd.Series(values)

    ours = Indicators.rsi(series, period=14)
    reference = _wilder_rsi_reference(series, period=14)

    assert ours.iloc[-1] == pytest.approx(reference.iloc[-1], rel=1e-4)


def test_rsi_is_bounded(closes):
    rsi = Indicators.rsi(closes, period=14).dropna()
    assert ((rsi >= 0) & (rsi <= 100)).all()


def test_rsi_uses_wilder_not_simple_mean(closes):
    """Wilder smoothing and a simple rolling mean must not agree.

    The codebase previously carried both implementations under the same name,
    silently producing different RSI values depending on the call site.
    """
    wilder = Indicators.rsi(closes, period=14)

    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    simple = 100 - (100 / (1 + gain / loss))

    assert wilder.iloc[14] != pytest.approx(simple.iloc[14], abs=0.01)


def test_sma_and_ema():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert Indicators.sma(s, 5).iloc[-1] == pytest.approx(3.0)
    # EMA seeds on the first value (adjust=False), alpha = 2/(5+1) = 1/3.
    assert Indicators.ema(s, 5).iloc[-1] == pytest.approx(3.3951, abs=1e-3)


def test_atr_on_constant_range():
    high = pd.Series([11.0] * 20)
    low = pd.Series([9.0] * 20)
    close = pd.Series([10.0] * 20)
    assert Indicators.atr(high, low, close, period=14).iloc[-1] == pytest.approx(2.0)


def test_bollinger_bands_straddle_the_mean():
    s = pd.Series(range(1, 41), dtype=float)
    upper, lower = Indicators.bollinger_bands(s, period=20, std_dev=2)
    middle = Indicators.sma(s, 20)
    assert upper.iloc[-1] > middle.iloc[-1] > lower.iloc[-1]
    # Symmetric around the mean.
    assert (upper.iloc[-1] - middle.iloc[-1]) == pytest.approx(middle.iloc[-1] - lower.iloc[-1])


def test_macd_histogram_is_line_minus_signal():
    s = pd.Series(range(1, 61), dtype=float)
    line, signal, hist = Indicators.macd(s)
    assert hist.iloc[-1] == pytest.approx(line.iloc[-1] - signal.iloc[-1])


def test_vwap_resets_each_session():
    """VWAP must accumulate within a session, not across the whole series.

    Two identical sessions must produce identical VWAP curves; a cumulative
    implementation carries day one's volume into day two and they diverge.
    """
    index = pd.to_datetime([
        "2026-01-01 09:15", "2026-01-01 09:16", "2026-01-01 09:17",
        "2026-01-02 09:15", "2026-01-02 09:16", "2026-01-02 09:17",
    ])
    price = pd.Series([100.0, 101.0, 102.0, 100.0, 101.0, 102.0], index=index)
    volume = pd.Series([10.0, 20.0, 30.0, 10.0, 20.0, 30.0], index=index)

    vwap = Indicators.vwap(price, price, price, volume)

    assert list(vwap.iloc[:3].round(6)) == list(vwap.iloc[3:].round(6))
    # First bar of a session is that bar's own typical price.
    assert vwap.iloc[3] == pytest.approx(100.0)


def test_vwap_is_volume_weighted():
    index = pd.to_datetime(["2026-01-01 09:15", "2026-01-01 09:16"])
    price = pd.Series([100.0, 200.0], index=index)
    volume = pd.Series([1.0, 3.0], index=index)

    vwap = Indicators.vwap(price, price, price, volume)
    # (100*1 + 200*3) / 4
    assert vwap.iloc[-1] == pytest.approx(175.0)


def test_calculate_all_populates_expected_columns():
    n = 250
    df = pd.DataFrame({
        "close": pd.Series(range(1, n + 1), dtype=float),
        "high": pd.Series(range(2, n + 2), dtype=float),
        "low": pd.Series(range(0, n), dtype=float),
        "volume": pd.Series([1000.0] * n),
    })
    out = Indicators.calculate_all(df)
    for col in ["rsi_14", "sma_50", "sma_200", "ema_9", "atr_14", "vwap",
                "bb_upper", "bb_lower", "macd_line", "macd_signal", "macd_hist"]:
        assert col in out.columns, col
        assert pd.notna(out[col].iloc[-1]), col


def test_calculate_all_rejects_missing_columns():
    with pytest.raises(ValueError):
        Indicators.calculate_all(pd.DataFrame({"close": [1.0, 2.0]}))
