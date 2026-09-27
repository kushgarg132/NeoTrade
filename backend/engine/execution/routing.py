"""Dispatches each Order to a real broker only if its strategy_name is a
key in live_by_strategy -- built once per /trading/start run
(backend/routers/trading.py) from the intersection of the user's toggled-
live strategies, an ACTIVE broker session, and backtest-gate eligibility.
Every other order, including one with no strategy_name at all, routes to
paper. This file is the one place that decision is made once a run is
already going -- get it right here and every caller upstream can be sloppy
about strategy_name and still never accidentally trade live.
"""

from typing import AsyncIterator

from backend.core.models import Fill, Order, Position
from backend.engine.execution.broker import BrokerExecutionClient


class RoutingExecutionClient:
    def __init__(
        self, paper, live_by_strategy: dict[str, BrokerExecutionClient],
    ) -> None:
        self._paper = paper
        self._live_by_strategy = live_by_strategy
        # Option contracts the runner has priced for paper. The broker
        # adapters place NSE equity orders only, so these never route live.
        self._options: set[str] = set()

    def _client_for(self, order: Order):
        if order.strategy_name is None or order.symbol in self._options:
            return self._paper
        return self._live_by_strategy.get(order.strategy_name, self._paper)

    async def submit(self, order: Order) -> str:
        return await self._client_for(order).submit(order)

    async def cancel(self, order_id: str) -> None:
        # order_id alone doesn't carry strategy_name -- cancel on every
        # client that might hold it; each store/queue simply no-ops if it
        # doesn't recognize the id.
        await self._paper.cancel(order_id)
        for client in self._live_by_strategy.values():
            await client.cancel(order_id)

    def positions(self) -> dict[str, Position]:
        merged = dict(self._paper.positions())
        for client in self._live_by_strategy.values():
            merged.update(client.positions())
        return merged

    async def fills(self) -> AsyncIterator[Fill]:
        async for fill in self._paper.fills():
            yield fill
        for client in self._live_by_strategy.values():
            async for fill in client.fills():
                yield fill

    def on_bar(self, symbol: str, bar) -> None:
        # Only paper's SimulatedExecutionClient needs the current bar's
        # close to fill against; a real broker fills at its own price.
        if hasattr(self._paper, "on_bar"):
            self._paper.on_bar(symbol, bar)

    def mark(self, symbol: str, price: float, timestamp, option: bool = False) -> None:
        if option:
            self._options.add(symbol)
        if hasattr(self._paper, "mark"):
            self._paper.mark(symbol, price, timestamp, option=option)

    async def poll_once(self) -> None:
        for client in self._live_by_strategy.values():
            if hasattr(client, "poll_once"):
                await client.poll_once()
