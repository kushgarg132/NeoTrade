"""How much the factor backtest is flattered by its universe (Phase 17.3.1).

The backtest on today's Nifty 200 list holds names that got into the index
*because* they rose (inclusion bias) and never the ones that fell out. `main`
measures that against the real Nifty 200 index and ETFs of NSE's factor indices.
`rotation` re-runs the autopilot's rotation on point-in-time membership
(`forecast/members.py`). Names Yahoo no longer has stay out, so some bias remains;
2019-02 to 2023-08 uses lists rolled forward from NSE's press releases.

    python -m backend.factor.survivorship [rotation]     (repo root; downloads ~2 min)

Results on 2026-10-07 are in docs/ROADMAP.md, 17.3.1.
"""
from dataclasses import replace

import pandas as pd

from backend.factor import data
from backend.factor.backtest import equal_weight, performance, simulate
from backend.factor.model import Params


def cagr(s: pd.Series) -> float:
    s = s.dropna()
    years = (s.index[-1] - s.index[0]).days / 365.25
    return (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1


def main() -> None:
    members = data.universe()
    closes = data.closes(members, start="2008-01-01")
    market = data.series(data.MARKET, start="2008-01-01")
    nifty200 = data.series("^CNX200", start="2008-01-01")


    # 1. Equal weight of today's members vs the real (point-in-time) Nifty 200, per year.
    print("year  EW(today's members)  ^CNX200  gap")
    for year in range(2012, 2027):
        start, end = f"{year}-01-01", f"{year}-12-31"
        ew = equal_weight(closes, start, end)
        idx = nifty200.loc[start:end]
        if len(idx) < 20:
            continue
        r_ew, r_idx = ew.iloc[-1] / ew.iloc[0] - 1, idx.iloc[-1] / idx.iloc[0] - 1
        print(f"{year}  {r_ew:+7.1%}  {r_idx:+7.1%}  {r_ew - r_idx:+6.1%}")
    ew_all = equal_weight(closes, "2012-01-01", "2026-12-31")
    print(f"2012-2026 CAGR: EW {cagr(ew_all):.1%}  ^CNX200 {cagr(nifty200.loc['2012':]):.1%}")

    # 2. Our simulator set up like NSE's factor indices vs the real ETF over the ETF's life.
    plain = dict(target_vol=None, trend_days=10**6, top_n=30, buffer=30, rebalance="monthly")
    for label, ticker, weight in (("Momentum 30", "MOMENTUM.NS", 1.0), ("Low Vol 30", "LOWVOLIETF.NS", 0.0)):
        etf = data.series(ticker, start="2008-01-01")
        start, end = etf.index[0], etf.index[-1]
        sim = simulate(closes, market, replace(Params(), momentum_weight=weight, **plain), start, end).equity
        print(f"{label}: {start.date()}..{end.date()}  ours {cagr(sim):.1%}  ETF {cagr(etf):.1%}  "
              f"gap {cagr(sim) - cagr(etf):+.1%}/yr")

    # 3. The shipped strategy, for reference.
    shipped = simulate(closes, market, Params(), "2012-01-01", "2026-12-31").equity
    print("shipped strategy 2012-2026:", performance(shipped))


def rotation(start: str = "2013-01-01", end: str = "2026-12-31") -> None:
    from itertools import product

    from backend.factor.model import ROTATION
    from backend.factor.validate import walk_forward
    from backend.forecast import members

    wanted = sorted(members.ever(rolled=True) | set(data.universe()))
    closes = data.closes(wanted, start="2008-01-01").dropna(axis=1, how="all")
    market = data.series(data.MARKET, start="2008-01-01")
    nifty200 = data.series("^CNX200", start="2008-01-01")
    closes = closes.reindex(market.index)
    member = members.mask(closes.index, closes.columns, rolled=True)
    print(f"prices for {closes.shape[1]} of {len(wanted)} names")
    for day, names in members.snapshots(rolled=True):
        if str(day) >= "2014":
            print(f"  list {day}: {len(names)} names, {len(names & set(closes.columns))} with prices")

    today = closes[[s for s in data.universe() if s in closes.columns]]
    runs = {"today's list": simulate(today, market, ROTATION, start, end),
            "point in time": simulate(closes, market, ROTATION, start, end, member=member)}
    for label, run in runs.items():
        m = run.metrics()
        print(f"{label:<14} CAGR {m['cagr']:.1%} Sharpe {m['sharpe']:.2f} maxDD {m['max_drawdown']:.0%} "
              f"turnover {m['turnover']:.1f}x cost {m['cost_drag']:.2%}")
    returns = closes.loc[start:end].pct_change(fill_method=None)
    ew = (1 + returns.where(member.loc[start:end]).mean(axis=1).fillna(0)).cumprod()
    index = nifty200.loc[start:end]
    print(f"EW point in time {cagr(ew):.1%}, real ^CNX200 price index {cagr(index):.1%} (no dividends, about 1.3% a year)")

    print("year  today   PIT   EW-PIT  ^CNX200  PIT-EW")
    pit, free = runs["point in time"].equity, runs["today's list"].equity
    for year in range(int(start[:4]), int(end[:4]) + 1):
        y = str(year)
        if y not in pit.index.strftime("%Y"):
            continue
        ret = lambda s: s.loc[y].iloc[-1] / s.loc[y].iloc[0] - 1
        print(f"{y} {ret(free):+6.1%} {ret(pit):+6.1%} {ret(ew):+6.1%} {ret(index):+6.1%} {ret(pit) - ret(ew):+6.1%}")

    variants = [replace(ROTATION, top_n=n, buffer=25 if n == 8 else 30, stop_atr=stop, breadth_min=breadth)
                for n, stop, breadth in product((8, 12), (None, 3.0), (None, 0.4))]
    wf = walk_forward(closes, market, start, end, variants, member=member)
    print(f"walk-forward point in time: {performance(wf.equity())}")
    print(f"deflated Sharpe {wf.dsr:.3f}; chosen {sorted({(p.top_n, p.stop_atr, p.breadth_min) for p in wf.chosen.values()}, key=str)}")

    etf = data.series("MOMENTUM.NS", start="2008-01-01")
    since = etf.index[0]
    print(f"since {since.date()}: rotation PIT {cagr(simulate(closes, market, ROTATION, since, end, member=member).equity):.1%}, "
          f"Momentum 30 ETF {cagr(etf):.1%}, ^CNX200 {cagr(nifty200.loc[since:]):.1%}")


if __name__ == "__main__":
    import sys

    rotation() if sys.argv[1:] == ["rotation"] else main()
