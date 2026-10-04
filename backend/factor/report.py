"""Walk-forward report for the factor strategy against its benchmarks.

    python -m backend.factor.report [--start 2009-06-01] [--save]

--save records the verdict in the backtest gate (strategy_backtests) under
STRATEGY_NAME. Network: yfinance (~25s for the Nifty 200).
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone

import pandas as pd

from backend.factor import backtest, data
from backend.factor.validate import grid, walk_forward

STRATEGY_NAME = "factor_momentum_lowvol"
DSR_THRESHOLD = 0.95
DRAWDOWN_MARGIN = 0.05   # may fall at most 5 points further than the worst benchmark
MIN_OOS_YEARS = 8


def verdict(strategy: dict, benchmarks: dict[str, dict], dsr: float, oos_years: float) -> dict:
    """The gate for the factor strategy: out-of-sample, net of costs, it must
    beat every benchmark's Sharpe, not draw down much worse than the worst of
    them, survive the deflated-Sharpe test, and cover enough years."""
    best_sharpe = max(b["sharpe"] for b in benchmarks.values())
    worst_dd = min(b["max_drawdown"] for b in benchmarks.values())
    checks = {
        "beats_benchmark_sharpe": strategy["sharpe"] > best_sharpe,
        "drawdown_ok": strategy["max_drawdown"] >= worst_dd - DRAWDOWN_MARGIN,
        "deflated_sharpe_ok": dsr >= DSR_THRESHOLD,
        "enough_years": oos_years >= MIN_OOS_YEARS,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run(start: str = "2009-06-01", end=None) -> dict:
    symbols = data.universe()
    closes = data.closes(symbols)
    market = data.series(data.MARKET)
    end = end or closes.index[-1]
    wf = walk_forward(closes, market, start, end, grid())
    oos_start, oos_end = wf.returns.index[0], wf.returns.index[-1]
    strategy = backtest.performance(wf.equity())
    benchmarks = {name: backtest.performance(backtest.buy_and_hold(data.series(t), oos_start, oos_end))
                  for name, t in data.BENCHMARKS.items()}
    benchmarks["Equal-weight Nifty 200 (same bias)"] = backtest.performance(
        backtest.equal_weight(closes, oos_start, oos_end))
    oos_years = len(wf.returns) / 252
    trial_costs = {str(p.momentum_weight) + "/" + str(p.top_n) + "/" + p.rebalance + "/" + str(p.target_vol):
                   r.metrics() for p, r in wf.trials.items()}
    return {
        "strategy": STRATEGY_NAME, "window": [str(oos_start.date()), str(oos_end.date())],
        "oos": strategy, "dsr": wf.dsr, "benchmarks": benchmarks,
        "verdict": verdict(strategy, benchmarks, wf.dsr, oos_years),
        "chosen": {y: f"mom={p.momentum_weight} n={p.top_n} {p.rebalance} vol={p.target_vol}"
                   for y, p in wf.chosen.items()},
        "variants_full_period": trial_costs,
    }


def _table(report: dict) -> str:
    rows = [("Strategy (walk-forward, net)", report["oos"])] + list(report["benchmarks"].items())
    lines = [f"{'':40} {'CAGR':>7} {'Vol':>6} {'Sharpe':>7} {'MaxDD':>7} {'Calmar':>7}"]
    for name, m in rows:
        lines.append(f"{name:40} {m['cagr']:7.1%} {m['vol']:6.1%} {m['sharpe']:7.2f} {m['max_drawdown']:7.1%} {m['calmar']:7.2f}")
    return "\n".join(lines)


async def _save(report: dict) -> None:
    from backend.database import db
    await db.connect_to_database()
    await db.db["strategy_backtests"].insert_one({
        "strategy": STRATEGY_NAME, "passed": report["verdict"]["passed"], "kind": "factor_walk_forward",
        "ran_at": datetime.now(timezone.utc), "report": json.loads(json.dumps(report, default=str)),
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2009-06-01")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    report = run(args.start)
    print(f"Out-of-sample {report['window'][0]} .. {report['window'][1]}")
    print(_table(report))
    print(f"Deflated Sharpe: {report['dsr']:.3f}  Verdict: {report['verdict']}")
    print("Chosen per year:", json.dumps(report["chosen"], indent=1))
    pd.set_option("display.width", 200)
    print(pd.DataFrame(report["variants_full_period"]).T[["cagr", "sharpe", "max_drawdown", "turnover", "cost_drag"]].round(3))
    if args.save:
        asyncio.run(_save(report))


if __name__ == "__main__":
    main()
