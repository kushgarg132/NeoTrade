"""backend.ml.features: 24 features, no look-ahead, labels equal the Lab's round trip."""

import numpy as np
import pandas as pd
import pytest

from backend.datalayer import bars
from backend.forecast import setups
from backend.lab.assumptions import DEFAULT, round_trip_return
from backend.ml.features import FEATURES, features, labels, long_table
from backend.tests.test_forecast_picks import _frames

H = 20


@pytest.fixture(scope="module")
def t():
    return setups.table(_frames(days=330, n=12))


def test_features_has_the_24_names(t):
    f = features(t)
    assert len(FEATURES) == 24 and list(f) == FEATURES
    assert all(f[k].shape == t["close"].shape for k in FEATURES)


def test_mom_vol_is_the_setup_score(t):
    r12_1, vol = setups._mom_vol_parts(t["close"])
    pd.testing.assert_frame_equal(features(t)["mom_vol"], r12_1 / vol.replace(0, np.nan))


def test_no_look_ahead_changing_later_bars_leaves_features_at_d_unchanged(t):
    d = t["close"].index[250]
    mutated = {k: v.copy() for k, v in t.items()}
    after = mutated["close"].index > d
    for k, v in mutated.items():
        v.loc[after] = v.loc[after] * 3 + 1  # every later bar changes, incl. the NIFTY series
    a, b = features(t), features(mutated)
    for k in FEATURES:
        pd.testing.assert_frame_equal(a[k].loc[:d], b[k].loc[:d], obj=k)
    assert not a["r5"].loc[after].equals(b["r5"].loc[after])  # the mutation did reach later rows


def test_labels_net_is_the_lab_round_trip_with_default_costs(t):
    net, nifty, label_end = labels(t, H)
    days, i = t["close"].index, 40
    want = round_trip_return(t["open"]["S3"].iloc[i + 1], t["close"]["S3"].iloc[i + 1 + H], DEFAULT)
    assert net["S3"].iloc[i] == pytest.approx(want)
    assert nifty.iloc[i] == pytest.approx(t["nifty_close"].iloc[i + 1 + H] / t["nifty_open"].iloc[i + 1] - 1)
    assert label_end.iloc[i] == days[i + 1 + H] and pd.isna(label_end.iloc[-1])


def test_long_table_every_fifth_date_labelled_and_consistent(t):
    df = long_table(features(t), t, H)
    days = list(t["close"].index)
    assert list(df.columns) == ["date", "symbol", *FEATURES, "net", "nifty", "excess", "up", "label_end"]
    assert {days.index(d) % 5 for d in df["date"]} == {0}
    assert df[["net", "nifty", "excess", "up", "label_end"]].notna().all().all()
    assert (df["excess"] == df["net"] - df["nifty"]).all()
    assert (df["up"] == (df["net"] > 0)).all()
    assert (df["label_end"] > df["date"]).all()
