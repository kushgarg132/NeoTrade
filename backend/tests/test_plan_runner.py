"""Phase 15.3: run() acts on a new plan version -- closes its exits, takes
on its stocks in play -- once per version."""

from datetime import datetime, timedelta, timezone

from backend.core.clock import SimClock
from backend.core.models import Bar, Position
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import StrategySpec
from backend.engine.runner import run
from backend.plan.gate import PlanGate

START = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
TOKENS = {1: "TCS", 2: "INFY"}


class _Quiet:
    """An intraday strategy that never signals; holds TCS in these tests."""

    def __init__(self):
        self.spec = StrategySpec(name="quiet", mode="INTRADAY", timeframe="5m", warmup_bars=1, universe=["TCS"])

    def on_start(self, ctx): ...
    def on_bar(self, ctx, bar): ...
    def on_fill(self, ctx, fill): ...

    def extend_universe(self, symbols):
        self.spec.universe = self.spec.universe + [s for s in symbols if s not in self.spec.universe]


class _Feed:
    def __init__(self, n):
        self._bars = [Bar(instrument_token=1, timeframe="5m", timestamp=START + timedelta(minutes=5 * i),
                          open=100, high=101, low=99, close=100, volume=1000) for i in range(n)]

    async def __aiter__(self):
        for bar in self._bars:
            yield bar


def _plan(version, **kw):
    return {"version": version, "trigger": "news:n1", "skip_day": False, "risk_multiplier": 1.0,
            "max_positions": 10, "allow": [], "add_symbols": [], "exits": [], **kw}


def _source(by_bar):
    """by_bar: [(first bar index, plan)] -- the plan in force from that bar."""
    async def source(now):
        i = int((now - START) / timedelta(minutes=5))
        current = None
        for start, plan in by_bar:
            if i >= start:
                current = plan
        return current
    return source


async def _run(by_bar, n=6, held=10.0, expand=None, live_holders=None, shadow_exit=None):
    portfolio = Portfolio()
    if held:
        portfolio.positions["TCS"] = Position(symbol="TCS", quantity=held, avg_price=100.0)
    execution = SimulatedExecutionClient()
    submitted = []
    original = execution.submit

    async def submit(order):
        submitted.append(order)
        return await original(order)
    execution.submit = submit
    await run(strategies=[_Quiet()], feed=_Feed(n), execution=execution, portfolio=portfolio, clock=SimClock(),
              symbol_for_token=dict(TOKENS), plan=PlanGate(_source(by_bar)), holders={"TCS": "quiet"},
              expand=expand, live_holders=live_holders, shadow_exit=shadow_exit)
    return submitted, portfolio


async def test_plan_exit_closes_a_paper_position_once():
    v2 = _plan(2, exits=[{"symbol": "TCS", "reason": "guidance cut"}])
    orders, portfolio = await _run([(0, _plan(1)), (2, v2)])
    assert [(o.symbol, o.side.value, o.quantity, o.product) for o in orders] == [("TCS", "SELL", 10.0, "MIS")]
    assert orders[0].strategy_name == "quiet" and portfolio.positions["TCS"].quantity == 0


async def test_plan_exit_for_a_flat_symbol_does_nothing():
    orders, _ = await _run([(2, _plan(2, exits=[{"symbol": "TCS", "reason": "x"}]))], held=0)
    assert orders == []


async def test_plan_exit_on_a_live_position_is_only_shadowed():
    shadowed = []

    async def shadow(symbol, quantity, reason):
        shadowed.append((symbol, quantity, reason))
    orders, _ = await _run([(2, _plan(2, exits=[{"symbol": "TCS", "reason": "guidance cut"}]))],
                           live_holders={"quiet"}, shadow_exit=shadow)
    assert orders == [] and shadowed == [("TCS", 10.0, "guidance cut")]


async def test_added_symbol_is_expanded_once_and_backfilled_and_a_dropped_add_is_not_redone():
    calls = []

    async def expand(symbols):
        calls.append(symbols)
        return [Bar(instrument_token=2, timeframe="5m", timestamp=START, open=50, high=51, low=49, close=50,
                    volume=10, warmup=True)]
    await _run([(1, _plan(2, add_symbols=["INFY"])), (3, _plan(3, add_symbols=[]))], expand=expand)
    assert calls == [["INFY"]]


async def test_expand_error_is_logged_and_the_run_continues():
    async def expand(symbols):
        raise RuntimeError("no instrument")
    orders, _ = await _run([(1, _plan(2, add_symbols=["INFY"], exits=[{"symbol": "TCS", "reason": "x"}]))],
                           expand=expand)
    assert [o.symbol for o in orders] == ["TCS"]  # the same version's exit still happened
