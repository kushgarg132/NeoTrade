"""Feature and label tables for the ML ranking harness (research; nothing in the app imports this).

Features on day t use bars up to t only. A label is the net return of entering at t+1's
open and exiting at the close of t+1+H (`lab.assumptions.round_trip_return`, DEFAULT
slippage and CNC charges); NIFTY is measured over the identical window. The input table is
`forecast.picks.load`'s (`setups.table`).
"""

import numpy as np
import pandas as pd

from backend.forecast import setups
from backend.lab.assumptions import DEFAULT, round_trip_return
from backend.strategies.indicators import Indicators

STEP = 5  # neighbouring days are near-duplicates: sample every 5th

FEATURES = (
    [f"r{n}" for n in (5, 20, 60, 120, 252)]
    + ["r252_skip21", "vol20", "vol60", "mom_vol", "vratio1", "vratio5_60", "d52h", "d_sma200", "d_sma50",
       "rsi14", "atr_pct", "sig_breakout", "sig_pullback", "sig_momentum", "sig_low_vol",
       "mkt_r20", "mkt_r60", "mkt_sma200", "mkt_vol20"]
)


def features(t: dict) -> dict[str, pd.DataFrame]:
    """name -> wide frame (date x symbol), backward-looking only."""
    c, h, low, v = t["close"], t["high"], t["low"], t["volume"]
    ret = c.pct_change(fill_method=None)
    f = {f"r{n}": c / c.shift(n) - 1 for n in (5, 20, 60, 120, 252)}
    f["r252_skip21"] = c.shift(21) / c.shift(252) - 1
    f["vol20"], f["vol60"] = ret.rolling(20).std(), ret.rolling(60).std()
    f["mom_vol"] = f["r252_skip21"] / f["vol60"].replace(0, np.nan)  # = setups.momentum_vol's score
    avg20 = v.shift(1).rolling(20).mean()
    f["vratio1"], f["vratio5_60"] = v / avg20, v.rolling(5).mean() / v.rolling(60).mean()
    f["d52h"] = c / c.rolling(252, min_periods=252).max() - 1
    f["d_sma200"] = c / c.rolling(200, min_periods=200).mean() - 1
    f["d_sma50"] = c / c.rolling(50).mean() - 1
    f["rsi14"] = Indicators.rsi(c, 14)
    tr = pd.concat([h - low, (h - c.shift()).abs(), (low - c.shift()).abs()]).groupby(level=0).max()
    f["atr_pct"] = tr.rolling(14).mean() / c
    # the Picks setups themselves; momentum/low_vol rank monthly, so carry the month's flag
    f["sig_breakout"] = setups.breakout(t).fillna(0)
    f["sig_pullback"] = setups.pullback(t).fillna(0)
    f["sig_momentum"] = setups.momentum(t).ffill(limit=21).notna().astype(float)
    f["sig_low_vol"] = setups.low_vol(t).ffill(limit=21).notna().astype(float)
    n = t["nifty_close"]
    market = {"mkt_r20": n / n.shift(20) - 1, "mkt_r60": n / n.shift(60) - 1,
              "mkt_sma200": n / n.rolling(200).mean() - 1, "mkt_vol20": n.pct_change().rolling(20).std()}
    for k, s in market.items():  # broadcast the market-wide series over the symbols
        f[k] = pd.DataFrame({sym: s for sym in c.columns})
    return {k: f[k] for k in FEATURES}


def labels(t: dict, horizon: int, step: int = 1) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """(net, nifty, label_end) by signal date; only every `step`-th row of `net` is computed (rest NaN).

    ponytail: one scalar charges call per cell; `step` keeps it to the sampled rows.
    """
    days = t["close"].index
    e = t["open"].shift(-1).to_numpy()
    x = t["close"].shift(-(1 + horizon)).to_numpy()
    net = np.full(e.shape, np.nan)
    for i in range(0, len(days), step):
        for j in np.flatnonzero(np.isfinite(e[i]) & np.isfinite(x[i]) & (e[i] > 0) & (x[i] > 0)):
            net[i, j] = round_trip_return(e[i, j], x[i, j], DEFAULT)
    nifty = t["nifty_close"].shift(-(1 + horizon)) / t["nifty_open"].shift(-1) - 1
    label_end = pd.Series(days, index=days).shift(-(1 + horizon))
    return pd.DataFrame(net, index=days, columns=t["close"].columns), nifty, label_end


def long_table(f: dict, t: dict, horizon: int, step: int = STEP) -> pd.DataFrame:
    """One row per (date, symbol) on every `step`-th date with a label."""
    net, nifty, label_end = labels(t, horizon, step)
    df = pd.DataFrame({k: f[k].stack(future_stack=True) for k in FEATURES})
    df.index.names = ["date", "symbol"]
    df["net"] = net.stack(future_stack=True)
    df = df[df["net"].notna()].reset_index()
    df["nifty"] = df["date"].map(nifty)
    df["label_end"] = df["date"].map(label_end)
    df = df[df["nifty"].notna()]
    df["excess"] = df["net"] - df["nifty"]
    df["up"] = (df["net"] > 0).astype(int)
    return df[["date", "symbol", *FEATURES, "net", "nifty", "excess", "up", "label_end"]].reset_index(drop=True)
