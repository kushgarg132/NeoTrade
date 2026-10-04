"""ExecutionClient that fills MARKET orders immediately at the current bar's
close. Costs are computed via the real Indian brokerage/tax model
(backend/engine/execution/costs.py), selected by the order's CNC/MIS
`product`.

This same class is meant to serve both backtest AND paper trading (per the
rework's plan: one execution path, different data feed). Do not fork a
second "paper" implementation.
"""

from typing import AsyncIterator

from backend.core.models import Bar, Fill, Order, Position
from backend.engine.execution.costs import calculate_indian_costs
from backend.engine.execution.options_costs import calculate_options_costs


class SimulatedExecutionClient:
    def __init__(self, slippage_bps: float = 0.0) -> None:
        # Backtests pass a slippage: a real market order pays the spread and
        # some impact, always against the trader. Paper trading keeps 0 --
        # it already fills at a live mark.
        self.slippage_bps = slippage_bps
        self._last_price: dict[str, float] = {}
        self._last_timestamp: dict = {}
        self._pending_fills: list[Fill] = []

    def on_bar(self, symbol: str, bar: Bar) -> None:
        """Runner-side hook, not part of the shared ExecutionClient
        protocol (a real broker client tracks its own prices) -- records
        the current bar's close so a MARKET order for this symbol fills
        against it."""
        self.mark(symbol, bar.close, bar.timestamp)

    def mark(self, symbol: str, price: float, timestamp) -> None:
        """The price a MARKET order for `symbol` fills at next. The runner
        calls it directly for an option contract, which has no bar of its
        own."""
        self._last_price[symbol] = price
        self._last_timestamp[symbol] = timestamp

    async def submit(self, order: Order) -> str:
        if order.order_type != "MARKET":
            raise NotImplementedError("SimulatedExecutionClient only fills MARKET orders today")

        price = self._last_price.get(order.symbol)
        timestamp = self._last_timestamp.get(order.symbol)
        if price is None or timestamp is None:
            raise ValueError(
                f"No current bar known for {order.symbol!r}; on_bar() must run before submit()"
            )

        if self.slippage_bps:
            price *= 1 + (self.slippage_bps if order.side.value == "BUY" else -self.slippage_bps) / 10_000
        costs = (
            calculate_options_costs(price, order.quantity, order.side) if order.contract is not None
            else calculate_indian_costs(price, order.quantity, order.side, order.product)
        )
        self._pending_fills.append(Fill(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            timestamp=timestamp,
            costs=costs,
        ))
        return order.id

    async def cancel(self, order_id: str) -> None:
        return None

    def positions(self) -> dict[str, Position]:
        # ponytail: the runner's own Portfolio is the book of record for
        # backtest/paper -- this satisfies the protocol shape for parity
        # with a future real-broker client, add real bookkeeping here only
        # if something starts reading it.
        return {}

    async def fills(self) -> AsyncIterator[Fill]:
        pending, self._pending_fills = self._pending_fills, []
        for fill in pending:
            yield fill
