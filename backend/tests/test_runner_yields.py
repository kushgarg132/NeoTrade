"""runner.run yields to the event loop during a replay: a long scan must not
starve other tasks (the ingest leader lock lapsed on 2026-10-15)."""

import asyncio

from backend.core.clock import SimClock
from backend.engine import runner
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.portfolio import Portfolio
from backend.tests.test_runner_warmup import _bar, _ListFeed


async def test_replay_lets_other_tasks_run():
    ticks = []

    async def ticker():
        while True:
            ticks.append(1)
            await asyncio.sleep(0)

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    before = len(ticks)
    feed = _ListFeed([_bar(i, 100.0, True) for i in range(5 * runner.YIELD_EVERY_BARS)])
    await runner.run(strategies=[], feed=feed, execution=SimulatedExecutionClient(), portfolio=Portfolio(),
                     clock=SimClock(), symbol_for_token=feed.symbol_for_token)
    task.cancel()
    assert len(ticks) - before >= 4  # the other task ran during the replay, not only after
