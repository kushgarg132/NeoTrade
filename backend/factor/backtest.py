"""Daily, mark-to-market backtest of the factor portfolio (backend/factor/model.py).

Honest by construction:
- the book is decided on the close of a rebalance day and traded on the
  NEXT day's close, so no decision uses a price it trades at;
- every trade pays the real delivery charges (engine/execution/costs.py)
  plus adverse slippage, in whole shares;
- equity is cash + every position marked at that day's close, so drawdown
  and Sharpe see unrealised losses;
- idle cash earns the risk-off sleeve's yield (a liquid ETF), which is also
  where the money sits whenever the trend filter is off.

Survivorship: callers pass today's index members, so results are biased
upward; compare against `equal_weight` of the same universe, which carries
the same bias.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.core.models import Side
from backend.engine.execution.costs import calculate_indian_costs
from backend.factor import model
from backend.factor.model import Params

SLIPPAGE_BPS = 10.0
RISK_OFF_YIELD = 0.065  # liquid ETF (e.g. LIQUIDBEES), annual


@dataclass
class Result:
    equity: pd.Series
    costs: float = 0.0
    traded: float = 0.0          # rupee value of every trade
    rebalances: int = 0
    books: list = field(default_factory=list)  # (decision day, {symbol: weight}, exposure)

    def metrics(self) -> dict:
        m = performance(self.equity)
        years = max(len(self.equity) / model.YEAR, 1e-9)
        avg = float(self.equity.mean())
        m.update(turnover=self.traded / avg / years, cost_drag=self.costs / avg / years,
                 rebalances=self.rebalances)
        return m


def performance(equity: pd.Series) -> dict:
    """CAGR, annual volatility, Sharpe (rf = 0), max drawdown, Calmar."""
    equity = equity.dropna()
    returns = equity.pct_change().dropna()
    years = len(returns) / model.YEAR
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0
    vol = returns.std() * np.sqrt(model.YEAR)
    sharpe = returns.mean() / returns.std() * np.sqrt(model.YEAR) if returns.std() else 0.0
    drawdown = float((equity / equity.cummax() - 1).min())
    return {"cagr": float(cagr), "vol": float(vol), "sharpe": float(sharpe), "max_drawdown": drawdown,
            "calmar": float(cagr / -drawdown) if drawdown < 0 else 0.0}


def rebalance_days(index: pd.DatetimeIndex, how: str) -> set:
    """Last trading day of each month (or quarter)."""
    frame = pd.Series(index, index=index)
    key = [index.year, index.month] if how == "monthly" else [index.year, index.quarter]
    return set(frame.groupby(key).max())


def simulate(closes: pd.DataFrame, market: pd.Series, params: Params, start, end,
             capital: float = 1_000_000.0, slippage_bps: float = SLIPPAGE_BPS,
             risk_off_yield: float = RISK_OFF_YIELD) -> Result:
    prices = closes.ffill()  # a missing day (halt, delisting) keeps its last price
    days = prices.loc[start:end].index
    decide_on = rebalance_days(days, params.rebalance)
    daily_yield = (1 + risk_off_yield) ** (1 / model.YEAR) - 1
    shares: dict[str, int] = {}
    cash = capital
    pending = None
    result = Result(equity=pd.Series(dtype=float))
    values = []

    for day in days:
        row = prices.loc[day]
        cash *= 1 + daily_yield
        if pending is not None:
            cash = _trade(shares, cash, row, pending, slippage_bps, result)
            pending = None
        equity = cash + sum(n * row[s] for s, n in shares.items() if np.isfinite(row[s]))
        values.append(equity)
        if day in decide_on:
            book, level = model.target_book(closes, market, day, set(shares), params)
            pending = book
            result.rebalances += 1
            result.books.append((day, book.round(4).to_dict(), level))

    result.equity = pd.Series(values, index=days, name="equity")
    return result


def _trade(shares: dict, cash: float, row: pd.Series, book: pd.Series, slippage_bps: float,
           result: Result) -> float:
    equity = cash + sum(n * row[s] for s, n in shares.items() if np.isfinite(row[s]))
    targets = {s: int(w * equity // row[s]) for s, w in book.items() if np.isfinite(row[s]) and row[s] > 0}
    orders = {s: targets.get(s, 0) - n for s, n in shares.items()}
    orders.update({s: q for s, q in targets.items() if s not in shares})
    # Sells first so their cash funds the buys.
    for symbol, delta in sorted(orders.items(), key=lambda kv: kv[1]):
        if delta == 0 or not np.isfinite(row[symbol]):
            continue
        side = Side.BUY if delta > 0 else Side.SELL
        qty = abs(delta)
        price = row[symbol] * (1 + (slippage_bps if side == Side.BUY else -slippage_bps) / 10_000)
        if side == Side.BUY:
            qty = min(qty, int(cash // (price * 1.003)))  # never borrow
            if qty <= 0:
                continue
        costs = calculate_indian_costs(price, qty, side, "CNC")
        value = price * qty
        cash += -value - costs if side == Side.BUY else value - costs
        shares[symbol] = shares.get(symbol, 0) + (qty if side == Side.BUY else -qty)
        if shares[symbol] == 0:
            del shares[symbol]
        result.costs += costs
        result.traded += value
    return cash


def buy_and_hold(series: pd.Series, start, end, capital: float = 1_000_000.0) -> pd.Series:
    s = series.loc[start:end].ffill().dropna()
    return capital * s / s.iloc[0]


def equal_weight(closes: pd.DataFrame, start, end, capital: float = 1_000_000.0) -> pd.Series:
    """Every available member, equal weight, rebalanced daily, no costs --
    a generous benchmark that shares the universe's survivorship bias."""
    returns = closes.loc[start:end].pct_change(fill_method=None).mean(axis=1).fillna(0)
    return capital * (1 + returns).cumprod()
