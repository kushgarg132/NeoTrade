"""Research only (not wired anywhere): are there NEW rule-based daily setups that beat the live ones?

    python -m backend.forecast.research.new_setups_tool DUMP.pkl [RESULTS.pkl]

DUMP.pkl = pickle of (daily_bars DataFrame [symbol, date, ohlcv], {}) copied read-only from production
(same file format as perstock_experiment_tool). Conventions are the Picks ones: `setups.table`,
`study.events` (signal on close t, entry t+1 open, exit close t+1+H, net of 10 bps slippage per side and
CNC charges, NIFTY over the same window, one event per stock per horizon window via `study.kept`),
excess = net - NIFTY, test years = the years `study.walk_forward` would test (>= 30 matured events).
The rules have no fitted parameters, so "out of sample" only means "years after the first 30 events";
the thresholds below were fixed before looking, but the family was designed with the history in view.

Per variant x horizon (20/40/60): n, fires/month, median net, p10/p90, P(up), P(beat NIFTY), OOS excess
per trade, years positive, month-block bootstrap t (and a block-length ~ horizon t, the stricter of the
two decides), excess at 20 bps slippage, pre/post-2016 halves, overlap with the live setups, excess over
an all-stocks month-start baseline (the universe is today's list, so even a random pick beats NIFTY).
Multiple testing: Bonferroni over every variant x horizon tried (TRIALS printed).

Strict bar adds: excess over the same-month all-stocks baseline (survivorship + timing removed) > +1%, t >= 2.5.
Bar (all must hold): OOS excess > +2%/trade, positive in >= 70% of test years (years with >= 10 events),
bootstrap t >= 2.5, same at 20 bps, and mean excess > +1% in both the pre-2016 and the post-2016 half.
Universe: point-in-time index members (members.mask); ex-members have no bars yet, so survivors still dominate.
Caveats: no results/fundamental data, charges approximate at 20 bps.
"""

import math
import pickle
import sys
import time

import numpy as np
import pandas as pd

from backend.forecast import setups, study
from backend.lab.assumptions import Execution, round_trip_return

HORIZONS = (20, 40, 60)
SPLIT = pd.Timestamp("2016-01-01")
BAR = {"excess": 0.02, "years": 0.7, "t": 2.5, "half": 0.01, "adj": 0.01}
MIN_YEAR_N = 10
BOOT = 4000
SLIP_EXTRA = 0.002  # extra 10 bps per side -> ~0.2% of the round trip


# ---- signal builders (value on t uses rows <= t; NaN = no fire) -------------------------------------

def regime(t: dict) -> pd.Series:
    c = t["nifty_close"]
    return c > c.rolling(200, min_periods=200).mean()


_vol_ratio = setups._vol_ratio
results_drift = setups.results_drift


def _gate(fires: pd.DataFrame, t: dict) -> pd.DataFrame:
    return fires.where(pd.DataFrame(np.repeat(regime(t).to_numpy()[:, None], fires.shape[1], 1), index=fires.index, columns=fires.columns))


def breakout_var(t: dict, vol_min=1.5, base_range=None) -> pd.DataFrame:
    """setups.breakout with a different volume floor and optionally a >= 3-month base: the 63 closes BEFORE the
    breakout day span at most `base_range` (max/min - 1)."""
    close = t["close"]
    high_52w = close.rolling(252, min_periods=252).max()
    ratio = _vol_ratio(t)
    ok = (close >= high_52w) & (ratio >= vol_min)
    if base_range is not None:
        prior = close.shift(1)
        ok &= (prior.rolling(63, min_periods=63).max() / prior.rolling(63, min_periods=63).min() - 1) <= base_range
    return ratio.where(ok)


def rs_leaders(t: dict) -> pd.DataFrame:
    """Month's first trading day: top decile of 126-day return minus NIFTY's, and close above a rising 50- and
    200-day average (rising = higher than 20 days ago)."""
    close = t["close"]
    rs = close.pct_change(126, fill_method=None).sub(t["nifty_close"].pct_change(126), axis=0)
    s50, s200 = close.rolling(50, min_periods=50).mean(), close.rolling(200, min_periods=200).mean()
    trend = (close > s50) & (close > s200) & (s50 > s50.shift(20)) & (s200 > s200.shift(20))
    out = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for day in setups._month_starts(close.index):
        r = rs.loc[day].dropna()
        if len(r) < 10:
            continue
        top = r[r >= r.quantile(0.9)]
        top = top[trend.loc[day, top.index]]
        out.loc[day, top.index] = top.values
    return out


def sector_rs(t: dict, trend=False, hot=False) -> pd.DataFrame:
    """Month's first trading day: top decile (among index members) of 126-day return minus the equal-weight 126-day
    return of the stock's sector peers (sectors with >= 3 stocks that day). `trend`: close above a rising 50- and
    200-day average as in rs_leaders. `hot`: the sector itself beat NIFTY over the 126 days."""
    close = t["close"]
    ret = close.pct_change(126, fill_method=None)
    sector = pd.Series(t["sector"]).reindex(close.columns)
    s50, s200 = close.rolling(50, min_periods=50).mean(), close.rolling(200, min_periods=200).mean()
    up = (close > s50) & (close > s200) & (s50 > s50.shift(20)) & (s200 > s200.shift(20))
    nifty = t["nifty_close"].pct_change(126)
    out = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for day in setups._month_starts(close.index):
        r = setups._in_index(t, day, ret.loc[day].dropna())
        g = r.groupby(sector.reindex(r.index))
        peers = g.transform("mean").where(g.transform("count") >= 3)
        rs = (r - peers).dropna()
        if hot:
            rs = rs[peers.reindex(rs.index) > nifty.loc[day]]
        if len(rs) < 10:
            continue
        top = rs[rs >= rs.quantile(0.9)]
        if trend:
            top = top[up.loc[day, top.index]]
        out.loc[day, top.index] = top.values
    return out


def gap_hold(t: dict, gap_min=0.04, vol_min=2.0, days=3) -> pd.DataFrame:
    """Gap-up day g: open >= gap_min above the prior close on >= vol_min x its 20-day volume. Fires on g+3 if every
    close on g+1..g+3 stays >= the gap day's low (price/volume only, no results data)."""
    close, open_, low = t["close"], t["open"], t["low"]
    cond = ((open_ / close.shift(1) - 1) >= gap_min) & (_vol_ratio(t) >= vol_min)
    ok = cond.shift(days, fill_value=False).astype(bool)
    floor = low.shift(days)
    for k in range(days):
        ok &= close.shift(k) >= floor
    return (open_ / close.shift(1) - 1).shift(days).where(ok)


def vcp(t: dict, vol_min=None, sma200=False) -> pd.DataFrame:
    """The 20 days before t had a (high-low)/close range in the bottom decile of the stock's own trailing 2 years,
    and t closes above that range's high."""
    close, high, low = t["close"], t["high"], t["low"]
    hi20 = high.rolling(20, min_periods=20).max()
    width = ((hi20 - low.rolling(20, min_periods=20).min()) / close).shift(1)
    squeezed = width <= width.rolling(504, min_periods=252).quantile(0.1)
    ok = squeezed & (close > hi20.shift(1))
    if vol_min:
        ok &= _vol_ratio(t) >= vol_min
    if sma200:
        ok &= close > close.rolling(200, min_periods=200).mean()
    return (1 / width).where(ok)  # tighter squeeze = higher strength


def every_month(t: dict) -> pd.DataFrame:
    """Baseline: every stock on each month's first trading day (what a random pick earns in this universe)."""
    c = t["close"]
    out = pd.DataFrame(np.nan, index=c.index, columns=c.columns)
    out.loc[setups._month_starts(c.index)] = 1.0
    return out.where(c.notna())


def variants(t: dict) -> dict:
    """name -> thunk giving fires; the trial list."""
    b = lambda **kw: (lambda: breakout_var(t, **kw))
    return {
        "bo_vol2": b(vol_min=2.0), "bo_vol3": b(vol_min=3.0),
        "bo_base25": b(base_range=0.25), "bo_base15": b(base_range=0.15),
        "bo_regime": lambda: _gate(breakout_var(t), t),
        "bo_vol2_regime": lambda: _gate(breakout_var(t, vol_min=2.0), t),
        "bo_base25_regime": lambda: _gate(breakout_var(t, base_range=0.25), t),
        "mv_regime": lambda: _gate(setups.momentum_vol(t), t),
        "rs_leaders": lambda: rs_leaders(t),
        "rs_leaders_regime": lambda: _gate(rs_leaders(t), t),
        "gap4_vol2_hold3": lambda: gap_hold(t),
        "gap4_vol3_hold3": lambda: gap_hold(t, vol_min=3.0),
        "gap4_vol2_hold3_regime": lambda: _gate(gap_hold(t), t),
        "vcp": lambda: vcp(t), "vcp_vol15": lambda: vcp(t, vol_min=1.5),
        "vcp_regime": lambda: _gate(vcp(t), t), "vcp_above200": lambda: vcp(t, sma200=True),
        "sector_rs": lambda: sector_rs(t), "sector_rs_trend": lambda: sector_rs(t, trend=True),
        "sector_rs_hot": lambda: sector_rs(t, hot=True),
        "results_up4_vol2": lambda: results_drift(t),
        "results_up4_vol2_regime": lambda: _gate(results_drift(t), t),
        "results_gap3_vol2_hold3": lambda: results_drift(t, move_min=0.03, gap=True, days=3),
    }


# ---- statistics ----------------------------------------------------------------------------------

class H:  # the only thing study.events reads off a setup
    def __init__(self, horizon):
        self.horizon = horizon


def events(t: dict, fires: pd.DataFrame, horizon: int) -> pd.DataFrame:
    ev = study.events(t, H(horizon), fires)
    ev["excess"] = ev["net"] - ev["nifty"]
    ev["excess20"] = ev["excess"] - SLIP_EXTRA * (1 + ev["gross"])  # extra slippage, first order
    return ev


def block_t(ev: pd.DataFrame, col: str, months: int, rng) -> dict:
    """Mean of `col` with the t from resampling whole `months`-month blocks (events in a block move together)
    and a cluster-robust t over the same blocks."""
    if len(ev) < 5:
        return {"mean": np.nan, "boot_t": np.nan, "clu_t": np.nan, "p": np.nan}
    m = ev["signal"].dt.year * 12 + ev["signal"].dt.month
    g = ev.assign(b=(m - m.min()) // months).groupby("b")[col].agg(["sum", "count"])
    s, n = g["sum"].to_numpy(), g["count"].to_numpy()
    mean = s.sum() / n.sum()
    idx = rng.integers(0, len(s), (BOOT, len(s)))
    means = s[idx].sum(1) / n[idx].sum(1)
    boot = mean / means.std(ddof=1) if means.std() > 0 else np.nan
    se = math.sqrt(((s - mean * n) ** 2).sum()) / n.sum()
    return {"mean": float(mean), "boot_t": float(boot), "clu_t": float(mean / se) if se else np.nan,
            "p": math.erfc(abs(boot) / math.sqrt(2)) if np.isfinite(boot) else np.nan}


def overlap(ev: pd.DataFrame, other: pd.DataFrame) -> float:
    """Share of ev's events with an `other` event on the same stock whose signal is within 7 calendar days."""
    if ev.empty or other.empty:
        return float("nan")
    a = ev[["symbol", "signal"]].sort_values("signal")
    b = other[["symbol", "signal"]].sort_values("signal").assign(hit=1)
    m = pd.merge_asof(a, b, on="signal", by="symbol", direction="nearest", tolerance=pd.Timedelta(days=7))
    return float(m["hit"].notna().mean())


def oos(ev: pd.DataFrame) -> pd.DataFrame:
    """Events in the years study.walk_forward tests."""
    wf = study.walk_forward(ev)
    return ev[ev["signal"].dt.year.isin([y["year"] for y in wf["years"]])]


def evaluate(name: str, h: int, ev: pd.DataFrame, live: dict, base: float, bmonth: pd.Series, rng) -> dict:
    if len(ev) < 30:
        return {"name": name, "h": h, "n": len(ev), "pass": False}
    o = oos(ev)
    if len(o) < 30:
        return {"name": name, "h": h, "n": len(ev), "pass": False}
    k = max(1, round(h / 21))
    ex, ex20 = block_t(o, "excess", 1, rng), block_t(o, "excess20", 1, rng)
    blk = block_t(o, "excess", k, rng)
    yrs = o.groupby(o["signal"].dt.year)["excess"].agg(["mean", "count"])
    yrs = yrs[yrs["count"] >= MIN_YEAR_N]
    pre, post = o[o["signal"] < SPLIT]["excess"], o[o["signal"] >= SPLIT]["excess"]
    months = max(1, (ev["signal"].max().year - ev["signal"].min().year) * 12 + ev["signal"].max().month - ev["signal"].min().month)
    st = study.stats(ev)
    # strict: excess over what ANY stock earned that signal month (removes survivorship drift and market timing)
    o = o.assign(adj=o["excess"] - o["signal"].dt.to_period("M").map(bmonth).fillna(base).to_numpy())
    adj = block_t(o, "adj", k, rng)
    t_eff = min(ex["boot_t"], blk["boot_t"])
    r = {
        "name": name, "h": h, "n": len(ev), "per_month": len(ev) / months,
        "median": st["median"], "p10": st["p10"], "p90": st["p90"], "p_up": st["p_up"], "p_beat": st["p_beat_nifty"],
        "oos_n": len(o), "oos_x": ex["mean"], "yrs_pos": int((yrs["mean"] > 0).sum()), "yrs": len(yrs),
        "boot_t": ex["boot_t"], "clu_t": ex["clu_t"], "blk_t": blk["boot_t"], "t": t_eff,
        "p_adj": min(1.0, ex["p"] * TRIALS) if np.isfinite(ex["p"]) else np.nan,
        "x20": ex20["mean"], "t20": ex20["boot_t"], "pre": pre.mean() if len(pre) else np.nan,
        "post": post.mean() if len(post) else np.nan, "pre_n": len(pre), "post_n": len(post),
        "vs_base": ex["mean"] - base, "adj": adj["mean"], "adj_t": adj["boot_t"], "adj_padj": min(1.0, adj["p"] * TRIALS),
        **{f"ov_{k_}": overlap(ev, v) for k_, v in live.items()},
    }
    r["pass"] = bool(
        r["oos_x"] > BAR["excess"] and len(yrs) and r["yrs_pos"] / r["yrs"] >= BAR["years"] and t_eff >= BAR["t"]
        and r["x20"] > BAR["excess"] and ex20["boot_t"] >= BAR["t"]
        and r["pre"] > BAR["half"] and r["post"] > BAR["half"]
    )
    r["strict"] = bool(r["pass"] and r["adj"] > BAR["adj"] and r["adj_t"] >= BAR["t"])
    r["bonf"] = bool(np.isfinite(r["p_adj"]) and r["p_adj"] < 0.05)
    return r


TRIALS = 0


def load(path: str, results: str = None):
    from backend.forecast import members

    with open(path, "rb") as f:
        df, sectors = pickle.load(f)
    df["date"] = pd.to_datetime(df["date"])
    t = setups.table({s: g.set_index("date").sort_index() for s, g in df.groupby("symbol")})
    t["member"] = members.mask(t["close"].index, t["close"].columns)  # as picks.load: each day's own index
    t["sector"] = sectors
    if results:
        with open(results, "rb") as f:
            t["results"] = pickle.load(f)
    return t


def run(path: str, results: str = None) -> list:
    global TRIALS
    t0 = time.perf_counter()
    t = load(path, results)
    rng = np.random.default_rng(0)
    V = variants(t)
    TRIALS = len(V) * len(HORIZONS)
    print(f"stocks {t['close'].shape[1]}, days {len(t['close'])} {t['close'].index[0].date()}..{t['close'].index[-1].date()}; "
          f"variants {len(V)} x horizons {len(HORIZONS)} = {TRIALS} trials (Bonferroni over these)")
    live = {}
    for s in setups.SETUPS:
        live[s.name] = study.events(t, s, s.signals(t))
    live_any = pd.concat(live.values(), ignore_index=True)
    live_ov = {"bo": live["breakout"], "mv": live["momentum_vol_60"], "any": live_any, **{f"s_{k}": v for k, v in live.items()}}
    base_fires = every_month(t)
    for h in HORIZONS:
        b = events(t, base_fires, h)
        BASE[h] = oos(b)["excess"].mean()
        BMONTH[h] = b.groupby(b["signal"].dt.to_period("M"))["excess"].mean()
        print(f"baseline all-stocks month-start h={h}: n={len(b)} OOS excess {BASE[h]:+.4f}/trade (what any pick earns here)")
    rows = []
    for h in HORIZONS:  # references, not counted as trials
        rows += [("[ref]breakout", h, events(t, setups.breakout(t), h)), ("[ref]mom_vol", h, events(t, setups.momentum_vol(t), h))]
    for name, fn in V.items():
        fires = fn()
        rows += [(name, h, events(t, fires, h)) for h in HORIZONS]
    res = [evaluate(n, h, ev, live_ov, BASE[h], BMONTH[h], rng) for n, h, ev in rows]
    print_table(res)
    print(f"\nruntime {time.perf_counter() - t0:.0f}s")
    return res


BASE: dict = {}
BMONTH: dict = {}


def print_table(res: list) -> None:
    f = lambda v, p=1: "  n/a" if v is None or not np.isfinite(v) else f"{v * 100:+.{p}f}"
    print(f"\n{'variant':24}{'h':>3}{'n':>6}{'/mo':>5} {'med%':>6}{'p10':>6}{'p90':>6}{'Pup':>5}{'Pbt':>5} | "
          f"{'OOSx%':>6}{'yrs+':>6}{'bt':>5}{'blk':>5}{'clu':>5}{'padj':>6} | {'x20%':>6}{'pre%':>6}{'post%':>6} | "
          f"{'ovBO':>5}{'ovMV':>5}{'ovAll':>6}| {'vsBase':>6}{'adj%':>6}{'adjt':>5} pass")
    for r in res:
        if "oos_x" not in r:
            print(f"{r['name']:24}{r['h']:>3}{r['n']:>6}   (too few events)")
            continue
        print(f"{r['name']:24}{r['h']:>3}{r['n']:>6}{r['per_month']:>5.1f} {f(r['median']):>6}{f(r['p10'], 0):>6}{f(r['p90'], 0):>6}"
              f"{r['p_up'] * 100:>5.0f}{r['p_beat'] * 100:>5.0f} | {f(r['oos_x']):>6}{r['yrs_pos']:>3}/{r['yrs']:<2}"
              f"{r['boot_t']:>5.1f}{r['blk_t']:>5.1f}{r['clu_t']:>5.1f}{r['p_adj']:>6.2f} | {f(r['x20']):>6}{f(r['pre']):>6}{f(r['post']):>6} | "
              f"{r['ov_bo'] * 100:>5.0f}{r['ov_mv'] * 100:>5.0f}{r['ov_any'] * 100:>6.0f}| {f(r['vs_base']):>6}{f(r['adj']):>6}{r['adj_t']:>5.1f} "
              f"{'STRICT ' if r['strict'] else ''}{'PASS' if r['pass'] else ''}{'+bonf' if r['pass'] and r['bonf'] else ''}")
    print(f"\npassing the bar: {[(r['name'], r['h']) for r in res if r.get('pass')]}")
    for r in res:
        if r.get("strict"):
            print(f"  STRICT {r['name']} h={r['h']}: adj excess {r['adj'] * 100:+.2f}% t {r['adj_t']:.1f} Bonferroni p {r['adj_padj']:.3f}; overlap "
                  + ", ".join(f"{k[2:]} {v:.0%}" for k, v in r.items() if k.startswith("ov_s_")))
    print(f"STRICT (bar + excess over the same-month all-stocks baseline > +1% with t >= 2.5): {[(r['name'], r['h']) for r in res if r.get('strict')]}")


def _check() -> None:
    # no look-ahead: truncating the table after t never changes a fire on or before t
    idx = pd.bdate_range("2015-01-01", periods=900)
    rng = np.random.default_rng(1)
    px = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, (900, 6)), 0)), index=idx, columns=list("ABCDEF"))
    tb = {"open": px * (1 + rng.normal(0, 0.01, px.shape)), "close": px, "high": px * 1.01, "low": px * 0.99,
          "volume": pd.DataFrame(rng.lognormal(10, 0.5, px.shape), index=idx, columns=px.columns),
          "nifty_close": px.mean(axis=1), "nifty_open": px.mean(axis=1), "sector": dict(zip(px.columns, "xxxyyy")),
          "results": {c: list(idx[30::63] + pd.Timedelta(hours=16)) for c in px.columns}}
    cut = 700
    tc = {k: v if k in ("sector", "results") else v.iloc[:cut] for k, v in tb.items()}
    for name, fn in variants(tb).items():
        full, part = fn(), variants(tc)[name]()
        pd.testing.assert_frame_equal(full.iloc[:cut - 4], part.iloc[:cut - 4], obj=name)  # gap_hold looks back only
    # approximate 20 bps cost agrees with the exact charge model
    exact = round_trip_return(100.0, 110.0, Execution(slippage_bps=20), notional=study.NOTIONAL)
    approx = study.net_return(100.0, 110.0) - SLIP_EXTRA * 1.10
    assert abs(exact - approx) < 3e-4, (exact, approx)


if __name__ == "__main__":
    _check()
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
