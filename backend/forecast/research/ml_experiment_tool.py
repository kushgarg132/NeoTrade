"""Research only (not wired anywhere): does a cross-sectional LightGBM model
on bar features beat the Picks rule setups?

    python -m backend.forecast.research.ml_experiment_tool BARS.pkl

BARS.pkl is a pickled DataFrame of `daily_bars` rows (symbol, date, ohlcv).
Needs lightgbm + scikit-learn, which production does not install.

Same conventions as forecast/study.py: features on day t use bars up to t
only; entry at t+1's open, exit at the close of t+1+H; returns are net of
NSE delivery charges (`calculate_indian_costs`, CNC, study.NOTIONAL) and
NIFTY is measured over the identical window. Walk-forward per calendar year
Y: train on signal days whose label ended 1+H days before Y began (purge +
H-day embargo), test on Y. Survivorship: the universe is today's list.
"""

import pickle
import sys
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

from backend.components.quant.indicators import Indicators
from backend.core.models import Side
from backend.datalayer.bars import NIFTY
from backend.engine.execution.costs import calculate_indian_costs
from backend.forecast import setups, study

HORIZONS = (5, 20, 60)
STEP = 5  # train / IC sample every 5th day: neighbouring days are near-duplicates
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=31, min_child_samples=200,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, n_jobs=4, verbose=-1, random_state=0)


def load(path: str) -> tuple[dict, pd.DataFrame]:
    with open(path, "rb") as f:
        df = pickle.load(f)
    df["date"] = pd.to_datetime(df["date"])
    frames = {s: g.set_index("date").sort_index() for s, g in df.groupby("symbol")}
    t = setups.table(frames)
    low = pd.DataFrame({s: f["low"] for s, f in frames.items() if s != NIFTY}).reindex(t["close"].index)
    return t, low


def features(t: dict, low: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """name -> wide frame (or Series for market-wide), backward-looking only."""
    c, h, v = t["close"], t["high"], t["volume"]
    ret = c.pct_change(fill_method=None)
    f = {f"r{n}": c / c.shift(n) - 1 for n in (5, 20, 60, 120, 252)}
    f["r252_skip21"] = c.shift(21) / c.shift(252) - 1
    f["vol20"], f["vol60"] = ret.rolling(20).std(), ret.rolling(60).std()
    f["mom_vol"] = f["r252_skip21"] / f["vol60"]
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
    nret = n.pct_change()
    f["mkt_r20"], f["mkt_r60"] = n / n.shift(20) - 1, n / n.shift(60) - 1
    f["mkt_sma200"] = n / n.rolling(200).mean() - 1
    f["mkt_vol20"] = nret.rolling(20).std()
    return f


def labels(t: dict, horizon: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """(gross, net, nifty) for a signal on each day: entry t+1 open, exit t+1+H close."""
    entry, exit_ = t["open"].shift(-1), t["close"].shift(-(1 + horizon))
    gross = exit_ / entry - 1
    # charges depend only on turnover: buy = NOTIONAL, sell = NOTIONAL * (1 + gross)
    buy = calculate_indian_costs(1.0, study.NOTIONAL, Side.BUY, "CNC")
    sell = np.vectorize(lambda x: calculate_indian_costs(1.0, x, Side.SELL, "CNC"), otypes=[float])
    g = gross.to_numpy()
    net_np = np.full_like(g, np.nan)
    ok = np.isfinite(g) & (entry.to_numpy() > 0)
    net_np[ok] = g[ok] - (buy + sell(study.NOTIONAL * (1 + g[ok]))) / study.NOTIONAL
    net = pd.DataFrame(net_np, index=gross.index, columns=gross.columns)
    nifty = t["nifty_close"].shift(-(1 + horizon)) / t["nifty_open"].shift(-1) - 1
    return gross, net, nifty


def long_table(f: dict, t: dict, horizon: int) -> pd.DataFrame:
    gross, net, nifty = labels(t, horizon)
    cols = {k: v.stack(future_stack=True) for k, v in f.items() if isinstance(v, pd.DataFrame)}
    df = pd.DataFrame(cols)
    df.index.names = ["date", "symbol"]
    days = df.index.get_level_values("date")
    for k, v in f.items():
        if isinstance(v, pd.Series):
            df[k] = v.reindex(days).to_numpy()
    df["gross"] = gross.stack(future_stack=True)
    df["net"] = net.stack(future_stack=True)
    df["nifty"] = nifty.reindex(days).to_numpy()
    df["pos"] = t["close"].index.get_indexer(days)
    df = df[df["r20"].notna()]  # needs a month of history to say anything
    df["rank"] = df.groupby(level="date")["net"].rank(pct=True)
    return df


def spearman_by_day(df: pd.DataFrame, col: str) -> pd.Series:
    return df.groupby(level="date").apply(lambda g: g[col].rank().corr(g["net"].rank()) if len(g) > 20 else np.nan)


def t_over_months(ic: pd.Series) -> tuple[float, float, int]:
    m = ic.dropna().groupby(ic.dropna().index.to_period("M")).mean()
    return float(m.mean()), float(m.mean() / m.std(ddof=1) * np.sqrt(len(m))), len(m)


def portfolio(test: pd.DataFrame, col: str, horizon: int) -> dict:
    """Top decile by `col`, rebalanced every H days (non-overlapping), equal weight."""
    days = sorted(test.index.get_level_values("date").unique())
    rows, prev = [], None
    for d in days[::horizon]:
        g = test.xs(d, level="date").dropna(subset=["net"])
        if len(g) < 20:
            continue
        top = g.nlargest(max(1, len(g) // 10), col)
        names = set(top.index)
        turnover = 1.0 if prev is None else 1 - len(names & prev) / len(prev)
        cost = float((top["gross"] - top["net"]).mean())
        rows.append({"date": d, "net": top["net"].mean(), "gross": top["gross"].mean(), "cost": cost,
                     "turnover": turnover, "ew": g["net"].mean(), "nifty": g["nifty"].iat[0],
                     "pick_up": (top["net"] > 0).mean(), "pick_beat": (top["net"] > top["nifty"]).mean(),
                     "excess_per_pick": (top["net"] - top["nifty"]).mean()})
        prev = names
    p = pd.DataFrame(rows)
    ann = lambda r: float(np.prod(1 + r) ** (252 / (horizon * len(r))) - 1)
    # held-over names need no round trip: charge only the turned-over share
    held_adj = p["gross"] - p["turnover"] * p["cost"]
    return {"periods": len(p), "mean_net": p["net"].mean(), "mean_nifty": p["nifty"].mean(), "mean_ew": p["ew"].mean(),
            "ann_net": ann(p["net"]), "ann_net_turnover_adj": ann(held_adj), "ann_nifty": ann(p["nifty"]),
            "ann_ew": ann(p["ew"]), "beat_nifty": (p["net"] > p["nifty"]).mean(), "beat_ew": (p["net"] > p["ew"]).mean(),
            "pick_p_up": p["pick_up"].mean(), "pick_beat_nifty": p["pick_beat"].mean(),
            "excess_per_pick": p["excess_per_pick"].mean(), "turnover": p["turnover"].iloc[1:].mean(),
            "roundtrip_cost": p["cost"].mean()}


def reliability(p: np.ndarray, y: np.ndarray) -> list[tuple]:
    b = np.minimum((p * 10).astype(int), 9)
    return [(f"{k / 10:.1f}", int((b == k).sum()), float(p[b == k].mean()), float(y[b == k].mean()))
            for k in range(10) if (b == k).sum()]


def run(path: str) -> None:
    t, low = load(path)
    f = features(t, low)
    feats = list(f)
    days = t["close"].index
    years = sorted({d.year for d in days})
    print(f"universe {t['close'].shape[1]} stocks, {days[0].date()}..{days[-1].date()}, features {len(feats)}")
    oos60 = []
    for horizon in HORIZONS:
        df = long_table(f, t, horizon)
        labelled = df[df["net"].notna()]
        tests, fit_s = [], 0.0
        for year in years:
            start = days.searchsorted(pd.Timestamp(year=year, month=1, day=1))
            train = labelled[(labelled["pos"] <= start - 2 * horizon - 2) & (labelled["pos"] % STEP == 0)]
            test = df[df.index.get_level_values("date").year == year]
            if train.index.get_level_values("date").nunique() < 50 or test.empty:
                continue  # ~1 year of sampled days (bars only go back to late 2021)
            t0 = time.perf_counter()
            ranker = lgb.LGBMRegressor(**PARAMS).fit(train[feats], train["rank"])
            clf = lgb.LGBMClassifier(**PARAMS).fit(train[feats], (train["net"] > 0).astype(int))
            fit_s += time.perf_counter() - t0
            test = test.assign(pred=ranker.predict(test[feats]), p_up=clf.predict_proba(test[feats])[:, 1],
                               base_p=float((train["net"] > 0).mean()), year=year, train_rows=len(train))
            tests.append(test)
        oos = pd.concat(tests)
        if horizon == 60:
            oos60 = oos
        lab = oos[oos["net"].notna()]
        sampled = lab[lab["pos"] % STEP == 0]
        print(f"\n=== H={horizon}  test years {sorted(oos['year'].unique())}  train rows {sorted(set(oos['train_rows']))}  "
              f"fit time (ranker+clf, all years) {fit_s:.1f}s")
        for name, col in (("ML", "pred"), ("mom12-1/vol", "mom_vol")):
            ic, tstat, n_m = t_over_months(spearman_by_day(sampled, col))
            pf = portfolio(lab, col, horizon)
            print(f"  [{name}] rankIC mean {ic:+.4f} t {tstat:+.2f} over {n_m} months")
            print("   top decile: " + ", ".join(f"{k} {v:+.4f}" if isinstance(v, float) else f"{k} {v}" for k, v in pf.items()))
        for year, g in sampled.groupby("year"):
            ic = spearman_by_day(g, "pred").mean()
            print(f"   {year}: rankIC {ic:+.4f}  n_days {g.index.get_level_values('date').nunique()}")
        y = (sampled["net"] > 0).to_numpy(float)
        brier = float(np.mean((sampled["p_up"] - y) ** 2))
        base = float(np.mean((sampled["base_p"] - y) ** 2))
        print(f"  P(up) Brier model {brier:.4f} vs train base rate {base:.4f} (skill {1 - brier / base:+.3f}); realised {y.mean():.3f}")
        for row in reliability(sampled["p_up"].to_numpy(), y):
            print(f"    bucket {row[0]}: n {row[1]:6d} predicted {row[2]:.3f} realised {row[3]:.3f}")

    # head-to-head with the breakout rule on the same bars
    b = setups.BY_NAME["breakout"]
    res, fires = study.run(t, [b])
    r = res["breakout"]
    wf = r["walk_forward"]
    print(f"\n=== breakout rule (study.run on this snapshot): n {r['n']} median net {r['median']:+.4f} "
          f"p_up {r['p_up']:.3f} mean_excess {r['mean_excess']:+.4f}; walk-forward oos_n {wf['oos_n']} "
          f"oos_excess {wf['oos_excess']} t {wf['oos_t']} brier {wf['brier']}")
    ev = study.events(t, b, fires["breakout"])
    ev = ev.merge(oos60[["pred"]].reset_index(), left_on=["signal", "symbol"], right_on=["date", "symbol"])
    ev["excess"] = ev["net"] - ev["nifty"]
    if len(ev):
        hi = ev["pred"] >= ev["pred"].median()
        print(f"  breakout events in ML test years: n {len(ev)}, mean excess {ev['excess'].mean():+.4f}, median net {ev['net'].median():+.4f}")
        print(f"   ML60 score top half: n {hi.sum()} mean excess {ev.loc[hi, 'excess'].mean():+.4f} p_up {(ev.loc[hi, 'net'] > 0).mean():.3f}")
        print(f"   ML60 score low half: n {(~hi).sum()} mean excess {ev.loc[~hi, 'excess'].mean():+.4f} p_up {(ev.loc[~hi, 'net'] > 0).mean():.3f}")


def _check() -> None:
    """The vectorised charges must match study.net_return exactly."""
    t = {"open": pd.DataFrame({"A": [100.0, 100.0, 50.0, 50.0]}), "close": pd.DataFrame({"A": [100.0, 120.0, 90.0, 60.0]}),
         "nifty_open": pd.Series([1.0] * 4), "nifty_close": pd.Series([1.0] * 4)}
    _, net, _ = labels(t, 1)
    assert abs(net["A"].iat[0] - study.net_return(100.0, 90.0)) < 1e-9, net
    assert abs(net["A"].iat[1] - study.net_return(50.0, 60.0)) < 1e-9, net


if __name__ == "__main__":
    _check()
    run(sys.argv[1])
