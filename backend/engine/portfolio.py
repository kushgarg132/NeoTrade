"""In-memory position book. Shared by backtest/paper trading (the runner
calls `apply()` for every Fill it consumes); it is the book of record --
`ExecutionClient.positions()` is a separate, broker-facing concern that a
simulated client doesn't need to duplicate.
"""

from backend.core.models import Fill, Position, Side


class Portfolio:
    def __init__(self) -> None:
        self.positions: dict[str, Position] = {}

    def apply(self, fill: Fill) -> None:
        delta = fill.quantity if fill.side == Side.BUY else -fill.quantity
        pos = self.positions.get(fill.symbol)

        if pos is None or pos.quantity == 0:
            self.positions[fill.symbol] = Position(
                symbol=fill.symbol, quantity=delta, avg_price=fill.price, venue=fill.venue,
            )
            return

        same_direction = (pos.quantity > 0) == (delta > 0)
        if same_direction:
            new_quantity = pos.quantity + delta
            pos.avg_price = ((pos.avg_price * pos.quantity) + (fill.price * delta)) / new_quantity
            pos.quantity = new_quantity
            return

        # Opposite-direction fill: closes/reduces the existing position and
        # realizes P&L on the closed portion.
        closing_qty = min(abs(delta), abs(pos.quantity))
        direction = 1 if pos.quantity > 0 else -1
        pos.realized_pnl += direction * (fill.price - pos.avg_price) * closing_qty
        pos.quantity += delta

        if abs(pos.quantity) < 1e-9:
            pos.quantity = 0.0
            pos.avg_price = 0.0
        elif (pos.quantity > 0) != (direction > 0):
            # The fill overshot flat and flipped the position to the other
            # side; the remainder opens fresh at the fill price.
            pos.avg_price = fill.price

    def equity(self, mark_prices: dict[str, float]) -> float:
        """Cumulative P&L (realized + mark-to-market unrealized) across all
        positions. Not full account equity (no cash/margin tracking exists
        yet) -- that's out of this task's scope."""
        total = sum(pos.realized_pnl for pos in self.positions.values())
        for symbol, pos in self.positions.items():
            if pos.quantity == 0:
                continue
            price = mark_prices.get(symbol, pos.avg_price)
            pos.unrealized_pnl = pos.quantity * (price - pos.avg_price)
            total += pos.unrealized_pnl
        return total
