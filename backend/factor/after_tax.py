"""What the factor backtests leave after Indian capital-gains tax, and against an index fund.

Today's rates for every year: short-term 20%, long-term 12.5% over ₹1.25L a FY (mine/tax.py). Lots are
first in, first out. Losses carry forward without the 8-year limit. Charges reduce the gain, which is a
little kind to the frequent trader, since STT is not deductible. Interest on idle cash is taxed at SLAB.
Tax leaves the book the day after each FY ends, as a share of the book that day.

    python -m backend.factor.after_tax     (repo root; downloads ~2 min)
"""

from collections import defaultdict, deque
from datetime import date

import pandas as pd

from backend.factor import data
from backend.factor.backtest import performance, simulate
from backend.factor.model import ROTATION, Params
from backend.mine.tax import LTCG_EXEMPTION, LTCG_RATE, STCG_RATE, current_fy, is_long

SLAB = 0.30  # interest on idle cash and fund dividends, at the top rate
INDEX_DIVIDEND, INDEX_FEE = 0.013, 0.002  # a Nifty 200 fund: the price index leaves dividends out
EQUAL_WEIGHT = Params(momentum_weight=1.0, top_n=250, buffer=250, target_vol=None, trend_days=10**6,
                      rebalance="monthly", weighting="equal")


def realise(fills: list[tuple]) -> tuple[list[tuple], dict]:
    """fills: (day, symbol, side, quantity, price, charges). Returns sales as (day, gain, is long) and
    the lots left open, symbol -> [(day, quantity, price)]."""
    lots: dict[str, deque] = defaultdict(deque)  # [day, quantity, price, charges per share]
    sales = []
    for day, symbol, side, quantity, price, charges in fills:
        if side == "BUY":
            lots[symbol].append([day, float(quantity), price, charges / quantity])
            continue
        by_kind = {False: 0.0, True: 0.0}
        left, per_share = float(quantity), charges / quantity
        while left > 0 and lots[symbol]:
            lot = lots[symbol][0]
            take = min(left, lot[1])
            by_kind[is_long(lot[0], day)] += take * (price - lot[2] - lot[3] - per_share)
            lot[1] -= take
            left -= take
            if lot[1] <= 0:
                lots[symbol].popleft()
        sales += [(day, gain, kind) for kind, gain in sorted(by_kind.items()) if gain]
    return sales, {s: [(d, q, p) for d, q, p, _ in held] for s, held in lots.items() if held}


def tax_by_fy(sales: list[tuple]) -> dict[int, float]:
    gains: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for day, gain, long in sales:
        gains[current_fy(day)][long] += gain
    out, short_carry, long_carry = {}, 0.0, 0.0
    for fy in sorted(gains):
        short, long = gains[fy]
        short -= short_carry
        long -= long_carry
        if short < 0 < long:  # a short loss offsets long gains too; a long loss only long gains
            used = min(long, -short)
            long, short = long - used, short + used
        short_carry, long_carry = max(-short, 0.0), max(-long, 0.0)
        short, long = max(short, 0.0), max(long, 0.0)
        out[fy] = STCG_RATE * short + LTCG_RATE * max(long - LTCG_EXEMPTION, 0.0)
    return out


def after_tax_curve(equity: pd.Series, taxes: dict[int, float]) -> pd.Series:
    """`equity` with each FY's tax taken the first day after it ends, as a share of the book that day."""
    factor = pd.Series(1.0, index=equity.index)
    for fy, tax in sorted(taxes.items()):
        when = equity.index[equity.index >= pd.Timestamp(date(fy + 1, 4, 1))]
        if len(when) and tax > 0:
            factor.loc[when[0]:] *= 1 - min(tax / equity.loc[when[0]], 1.0)
    return equity * factor


def _report(label: str, result, prices: pd.DataFrame) -> None:
    sales, open_lots = realise([(day.date(), *rest) for day, *rest in result.fills])
    taxes = tax_by_fy(sales)
    interest: dict[int, float] = defaultdict(float)
    for day, amount in result.interest:
        interest[current_fy(day.date())] += amount
    for fy, amount in interest.items():
        taxes[fy] = taxes.get(fy, 0.0) + SLAB * amount
    curve = after_tax_curve(result.equity, taxes)
    end = curve.index[-1]
    last = prices.ffill().loc[end]
    final, _ = realise([(d, s, "BUY", q, p, 0.0) for s, held in open_lots.items() for d, q, p in held]
                       + [(end.date(), s, "SELL", sum(q for _, q, _ in held), float(last[s]), 0.0) for s, held in open_lots.items()])
    scale = curve.iloc[-1] / result.equity.iloc[-1]  # the book the tax left, against the one the sales came from
    exit_tax = sum(tax_by_fy(final).values()) * scale
    sold = curve.copy()
    sold.iloc[-1] -= exit_tax
    m, a, s = performance(result.equity), performance(curve), performance(sold)
    short = sum(g for _, g, long in sales if not long and g > 0)
    total = sum(g for _, g, _ in sales if g > 0) or 1
    print(f"{label:<14} before tax {m['cagr']:6.1%}  tax paid yearly {a['cagr']:6.1%}  sold at the end {s['cagr']:6.1%}  "
          f"Sharpe {a['sharpe']:.2f}  maxDD {a['max_drawdown']:.0%}  short-term share of gains {short / total:.0%}")


def index_fund(index: pd.Series, start, end) -> None:
    prices = index.loc[start:end].dropna()
    years = pd.Series(range(len(prices)), index=prices.index) / 252
    gross = prices * (1 + INDEX_DIVIDEND - INDEX_FEE) ** years
    net = prices * (1 + INDEX_DIVIDEND * (1 - SLAB) - INDEX_FEE) ** years
    capital = 1_000_000.0
    net, gross = capital * net / net.iloc[0], capital * gross / gross.iloc[0]
    sold = net.copy()
    sold.iloc[-1] -= LTCG_RATE * max(net.iloc[-1] - capital - LTCG_EXEMPTION, 0.0)
    print(f"{'Index fund':<14} before tax {performance(gross)['cagr']:6.1%}  tax paid yearly {performance(net)['cagr']:6.1%}  "
          f"sold at the end {performance(sold)['cagr']:6.1%}  Sharpe {performance(net)['sharpe']:.2f}  maxDD {performance(net)['max_drawdown']:.0%}")


def main() -> None:
    from backend.forecast import members

    wanted = sorted(members.ever(rolled=True) | set(data.universe()))
    market = data.series(data.MARKET, start="2008-01-01")
    closes = data.closes(wanted, start="2008-01-01").dropna(axis=1, how="all").reindex(market.index)
    member = members.mask(closes.index, closes.columns, rolled=True)
    index = data.series("^CNX200", start="2008-01-01")
    for start, end, note in (("2013-01-01", "2026-12-31", "whole period"), ("2014-02-01", "2019-02-01", "archived lists"),
                             ("2023-09-01", "2026-12-31", "archived lists")):
        print(f"--- {start} to {end} ({note})")
        for label, params in (("Rotation", ROTATION), ("Equal weight", EQUAL_WEIGHT)):
            _report(label, simulate(closes, market, params, start, end, member=member), closes)
        index_fund(index, start, end)


if __name__ == "__main__":
    main()
