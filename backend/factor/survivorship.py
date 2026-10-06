"""How much the factor backtest is flattered by its universe (Phase 17.3.1).

The backtest uses today's Nifty 200 list for every past date, so it holds
names that got into the index *because* they rose (inclusion bias) and never
the ones that fell out. No free point-in-time membership exists, so this
measures the bias against survivorship-free yardsticks instead of removing
it: the real Nifty 200 index, and ETFs that track NSE's own factor indices.

    python -m backend.factor.survivorship     (repo root; downloads ~2 min)

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


if __name__ == "__main__":
    main()
