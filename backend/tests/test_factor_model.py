"""The factor model's pure pieces: scores use only past data, selection
keeps holdings inside the buffer, weights respect the cap, and exposure
drops to the risk-off sleeve when the market trend breaks."""

import numpy as np
import pandas as pd
import pytest

from backend.factor import model
from backend.factor.model import Params


def _closes(days=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=days)
    drift = {"UP": 0.002, "FLAT": 0.0, "DOWN": -0.002, "CALM": 0.0005, "WILD": 0.0005}
    vol = {"UP": 0.01, "FLAT": 0.01, "DOWN": 0.01, "CALM": 0.002, "WILD": 0.04}
    data = {s: 100 * np.exp(np.cumsum(drift[s] + vol[s] * rng.standard_normal(days))) for s in drift}
    return pd.DataFrame(data, index=idx)


def test_scores_rank_trend_and_calm_and_ignore_the_future():
    closes = _closes()
    t = closes.index[300]
    scores = model.scores(closes, t, Params(momentum_weight=1.0))
    assert scores.idxmax() in ("UP", "CALM") and scores.idxmin() == "DOWN"
    # Changing prices after t must not change the score at t.
    future = closes.copy()
    future.loc[future.index > t] *= 5
    pd.testing.assert_series_equal(scores, model.scores(future, t, Params(momentum_weight=1.0)))
    lowvol = model.scores(closes, t, Params(momentum_weight=0.0))
    assert lowvol.idxmax() == "CALM" and lowvol.idxmin() == "WILD"


def test_scores_skip_symbols_without_a_full_year():
    closes = _closes()
    closes.loc[: closes.index[200], "WILD"] = np.nan
    assert "WILD" not in model.scores(closes, closes.index[300], Params()).index


def test_select_keeps_holdings_inside_the_buffer():
    scores = pd.Series({f"S{i}": 100 - i for i in range(40)})
    # S25 is held and ranks 26th: inside a 30 buffer it stays; S35 (36th) is dropped.
    chosen = model.select(scores, held={"S25", "S35"}, top_n=20, buffer=30)
    assert "S25" in chosen and "S35" not in chosen and len(chosen) == 20


def test_weights_are_inverse_vol_and_capped():
    vols = pd.Series({"A": 0.10, "B": 0.20, "C": 0.40, "D": 0.40})
    w = model.weights(vols, cap=0.35)
    assert w.sum() == pytest.approx(1.0)
    assert w.max() <= 0.35 + 1e-9 and w["A"] >= w["B"] > w["C"]


def test_exposure_targets_volatility_and_goes_risk_off_in_a_downtrend():
    idx = pd.bdate_range("2020-01-01", periods=300)
    rising = pd.Series(np.linspace(100, 200, 300), index=idx)
    falling = pd.Series(np.linspace(200, 100, 300), index=idx)
    calm = pd.Series(0.001, index=idx)  # daily returns of the candidate book
    wild = pd.Series(np.tile([0.03, -0.03], 150), index=idx)
    t = idx[-1]
    assert model.exposure(rising, calm, t, Params(target_vol=0.15)) == 1.0  # capped at fully invested
    assert 0 < model.exposure(rising, wild, t, Params(target_vol=0.15)) < 0.5
    assert model.exposure(falling, calm, t, Params(target_vol=0.15)) == 0.0
    assert model.exposure(rising, wild, t, Params(target_vol=None)) == 1.0


def test_avoid_list_is_respected():
    closes = _closes()
    scores = model.scores(closes, closes.index[300], Params(momentum_weight=1.0), avoid={"up"})
    assert "UP" not in scores.index
