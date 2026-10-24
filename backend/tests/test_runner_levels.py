"""runner.run enforces the stop/target an entry order carries on every run,
not just in run_backtest: a paper run exits at the level inside the bar."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.core.clock import SimClock
from backend.core.models import Bar, Intent, Side
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import StrategySpec
from backend.engine.runner import run

T0 = datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc)


class _BuyOnce:
    spec = StrategySpec(name="buy-once", mode="INTRADAY", timeframe="5m", warmup_bars=0, universe=["ITC"])
    fired = False

    def on_start(self, ctx): ...
    def on_fill(self, ctx, fill): ...

    def on_bar(self, ctx, bar):
        if not self.fired:
            self.fired = True
            ctx.submit(Intent(symbol="ITC", side=Side.BUY, strength=1.0, reason_codes=["t"],
                              stop_hint=95.0, target_hint=130.0))


class _Feed:
    def __init__(self, rows):
        self.rows = rows

    async def __aiter__(self):
        for i, (o, h, l, c) in enumerate(self.rows):
            yield Bar(instrument_token=1, timeframe="5m", timestamp=T0 + timedelta(minutes=5 * i),
                      open=o, high=h, low=l, close=c, volume=1000.0)


async def _paper(rows):
    execution, portfolio = SimulatedExecutionClient(fill_on_next_open=True), Portfolio()
    fills = []
    original = execution.fills

    async def recording():
        async for f in original():
            fills.append(f)
            yield f

    execution.fills = recording
    await run(strategies=[_BuyOnce()], feed=_Feed(rows), execution=execution, portfolio=portfolio,
              clock=SimClock(), symbol_for_token={1: "ITC"}, account_size=25_000.0, max_exposure=15_000.0,
              per_trade_cap=5_000.0)
    return fills, portfolio


@pytest.mark.asyncio
async def test_paper_run_exits_at_the_stop_inside_the_bar():
    fills, portfolio = await _paper([(100, 101, 99, 100), (102, 103, 101, 102), (101, 101, 94, 96), (96, 97, 95, 96)])
    assert [f.side for f in fills] == [Side.BUY, Side.SELL]
    assert fills[0].price == 102.0 and fills[1].price == 95.0   # next open in, the stop level out
    assert portfolio.positions["ITC"].quantity == 0


@pytest.mark.asyncio
async def test_paper_run_gap_through_the_stop_fills_at_the_open():
    fills, _ = await _paper([(100, 101, 99, 100), (102, 103, 101, 102), (92, 93, 90, 91)])
    assert fills[1].price == 92.0


@pytest.mark.asyncio
async def test_routing_run_paper_exit_fills_at_level_once_on_the_square_off_bar():
    """Routing (paper + empty live map): the stop hit on the 15:15 bar is one SELL at the level, no short."""
    from backend.engine.execution.routing import RoutingExecutionClient

    paper = SimulatedExecutionClient(fill_on_next_open=True)
    execution, portfolio, fills = RoutingExecutionClient(paper, {}), Portfolio(), []
    original = execution.fills

    async def recording():
        async for f in original():
            fills.append(f)
            yield f

    execution.fills = recording
    feed = _Feed([(100, 101, 99, 100), (102, 103, 101, 102), (102, 103, 101, 102), (101, 101, 94, 96), (96, 97, 95, 96)])
    feed_t0 = datetime(2026, 9, 1, 9, 30, tzinfo=timezone.utc)  # 15:00 IST; bar 3 is 15:15

    class _Shifted(_Feed):
        async def __aiter__(self):
            async for b in feed:
                yield b.model_copy(update={"timestamp": b.timestamp - T0 + feed_t0})

    await run(strategies=[_BuyOnce()], feed=_Shifted([]), execution=execution, portfolio=portfolio,
              clock=SimClock(), symbol_for_token={1: "ITC"}, account_size=25_000.0, max_exposure=15_000.0,
              per_trade_cap=5_000.0)
    assert [(f.side, f.price) for f in fills] == [(Side.BUY, 102.0), (Side.SELL, 95.0)]
    assert portfolio.positions["ITC"].quantity == 0
