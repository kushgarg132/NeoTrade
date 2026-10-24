"""Golden parity: one 5m fixture, one long that is stopped out intrabar, run
through run_backtest and through the paper wiring (run() with a ledger, as in
routers/trading.py::_launch_run). Backtest and paper are one system: entry,
exit, quantity, costs and net P&L must agree to the paisa."""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.clock import SimClock
from backend.core.models import Bar, Intent, PriceCandle, Side
from backend.engine.backtest import run_backtest
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.persistence import LedgerStore
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import StrategySpec
from backend.engine.runner import run
from backend.instruments.models import Instrument

T0 = datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
ROWS = [(100, 101, 99, 100), (102, 103, 101, 102), (101, 101, 94, 96), (96, 97, 95, 96)]  # bar 3 trades through the 95 stop
ACCOUNT = {"account_size": 25_000.0, "max_exposure": 15_000.0, "per_trade_cap": 5_000.0}


class _BuyOnce:
    def __init__(self):
        self.spec = StrategySpec(name="buy-once", mode="INTRADAY", timeframe="5m", warmup_bars=0, universe=["ITC"])
        self.fired = False

    def on_start(self, ctx): ...
    def on_fill(self, ctx, fill): ...

    def on_bar(self, ctx, bar):
        if not self.fired:
            self.fired = True
            ctx.submit(Intent(symbol="ITC", side=Side.BUY, strength=1.0, reason_codes=["t"],
                              stop_hint=95.0, target_hint=130.0))


class _Provider:
    async def history(self, instrument, interval, period=None, start=None, end=None):
        return [PriceCandle(symbol="ITC", timestamp=T0 + timedelta(minutes=5 * i), open=o, high=h, low=l,
                            close=c, volume=1000) for i, (o, h, l, c) in enumerate(ROWS)]

    async def quote(self, instrument):
        return {}


class _Feed:
    async def __aiter__(self):
        for i, (o, h, l, c) in enumerate(ROWS):
            yield Bar(instrument_token=1, timeframe="5m", timestamp=T0 + timedelta(minutes=5 * i),
                      open=o, high=h, low=l, close=c, volume=1000.0)


async def _backtest() -> dict:
    instrument = Instrument(exchange="NSE", tradingsymbol="ITC", name="ITC", instrument_token=1, exchange_token=1,
                            instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)
    result = await run_backtest([_BuyOnce()], _Provider(), [instrument], T0, T0 + timedelta(minutes=15), "5m", **ACCOUNT)
    buy, sell = result.trades
    return {"entry": buy["price"], "exit": sell["price"], "quantity": buy["quantity"],
            "costs": buy["costs"] + sell["costs"], "net_pnl": result.total_pnl}


async def _paper() -> dict:
    db = AsyncMongoMockClient()["parity"]
    ledger = LedgerStore(db, user_id="u", run_id="r")
    portfolio = Portfolio()
    await run(strategies=[_BuyOnce()], feed=_Feed(), execution=SimulatedExecutionClient(slippage_bps=10, fill_on_next_open=True),
              portfolio=portfolio, clock=SimClock(), symbol_for_token={1: "ITC"}, ledger=ledger, **ACCOUNT)
    [trade] = await ledger.get_trades(status="CLOSED")
    return {"entry": trade["entry_price"], "exit": trade["exit_price"], "quantity": trade["quantity"],
            "costs": trade["costs"], "net_pnl": trade["net_pnl"], "equity_costs": portfolio.costs_paid}


@pytest.mark.asyncio
async def test_backtest_and_paper_agree_to_the_paisa():
    bt, paper = await _backtest(), await _paper()
    assert bt["entry"] == pytest.approx(102 * 1.001) and bt["exit"] == pytest.approx(95 * 0.999)  # sanity: the fixture stops out
    assert paper["entry"] == pytest.approx(bt["entry"], abs=0.005)
    assert paper["exit"] == pytest.approx(bt["exit"], abs=0.005)
    assert paper["quantity"] == bt["quantity"]
    assert paper["costs"] == pytest.approx(bt["costs"], abs=0.005)
    assert paper["equity_costs"] == pytest.approx(bt["costs"], abs=0.005)
    assert paper["net_pnl"] == pytest.approx(bt["net_pnl"], abs=0.005)
