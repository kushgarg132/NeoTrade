"""Each order belongs to the strategy that emitted it, and the strategy that
opened a position owns it until it is flat. Before: owner_by_symbol mapped a
symbol to the LAST strategy listing it, so every intraday trade on
2026-10-05 was stamped rsi_momentum_scalp whatever made it, and one
strategy's sell could close another's buy."""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.clock import SimClock
from backend.core.models import Bar, Intent, Side
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.persistence import LedgerStore
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import StrategySpec
from backend.engine.runner import run

SYMBOL = "ATTRIB"


class _Scripted:
    """Emits `plan[i]` (a Side or None) on its i-th bar."""

    def __init__(self, name, plan):
        self.spec = StrategySpec(name=name, mode="INTRADAY", timeframe="5m", warmup_bars=0, universe=[SYMBOL])
        self.plan, self.i, self.fills = plan, 0, []

    def on_start(self, ctx):
        pass

    def on_bar(self, ctx, bar):
        side = self.plan[self.i] if self.i < len(self.plan) else None
        self.i += 1
        if side is not None:
            stop = bar.close - 5 if side == Side.BUY else bar.close + 5
            ctx.submit(Intent(symbol=SYMBOL, side=side, strength=1.0, reason_codes=[self.spec.name], stop_hint=stop))

    def on_fill(self, ctx, fill):
        self.fills.append(fill)


class _ListFeed:
    symbol_for_token = {7: SYMBOL}

    def __init__(self, n):
        start = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)  # 09:30 IST, far from the 15:15 square-off
        self._bars = [Bar(instrument_token=7, timeframe="5m", timestamp=start + timedelta(minutes=5 * i),
                          open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0) for i in range(n)]

    async def __aiter__(self):
        for bar in self._bars:
            yield bar


async def _run(strategies, n):
    db = AsyncMongoMockClient()["test_db"]
    ledger = LedgerStore(db, user_id="alice")
    await run(strategies=strategies, feed=_ListFeed(n), execution=SimulatedExecutionClient(),
              portfolio=Portfolio(), clock=SimClock(), symbol_for_token=_ListFeed.symbol_for_token,
              ledger=ledger, account_size=1_000_000.0, max_exposure=1_000_000.0)
    return ledger


@pytest.mark.asyncio
async def test_an_order_carries_the_strategy_that_emitted_it():
    maker = _Scripted("maker", [Side.BUY])
    bystander = _Scripted("bystander", [])  # listed last: the old map credited it
    ledger = await _run([maker, bystander], 1)
    trades = await ledger.get_trades()
    assert [t["strategy"] for t in trades] == ["maker"]
    assert len(maker.fills) == 1 and bystander.fills == []


@pytest.mark.asyncio
async def test_another_strategy_cannot_trade_a_stock_someone_else_holds():
    owner = _Scripted("owner", [Side.BUY, None, Side.SELL])
    other = _Scripted("other", [None, Side.SELL, None])
    ledger = await _run([owner, other], 3)
    trades = await ledger.get_trades()
    assert len(trades) == 1
    assert trades[0]["strategy"] == "owner" and trades[0]["status"] == "CLOSED"  # owner's own exit
    assert other.fills == []
