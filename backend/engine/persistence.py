"""Mongo-backed durability for the paper-trading ledger. The in-memory
Portfolio (backend/engine/portfolio.py) remains the per-run book of record
(runner.run applies fills to it directly, unchanged) -- this just mirrors
every order/fill/position snapshot into Mongo so a process restart doesn't
lose history, and so backend/routers/trading.py has something to query.

Every document is stamped with the owning `user_id` (and `run_id` where one
exists) and every read filters on it: the collections are shared across all
accounts, so an unscoped query would hand one user another's book.

Same db-handle pattern as backend/database.py (a motor/mongomock-motor
database passed in, not constructed here).
"""

import uuid
from datetime import datetime
from typing import Optional

from backend.core.models import Fill, Order, Position, Venue


class LedgerStore:
    def __init__(self, db, user_id: str, run_id: Optional[str] = None, on_change=None) -> None:
        self.user_id = user_id
        self.run_id = run_id
        # Injected rather than imported: the engine must not know a socket
        # exists. The trading routes pass one that publishes to the live hub;
        # backtests pass nothing.
        self.on_change = on_change
        self.orders = db["paper_orders"]
        self.fills = db["paper_fills"]
        self.positions = db["paper_positions"]
        self.trades = db["paper_trades"]

    def _stamp(self, doc: dict) -> dict:
        return {**doc, "user_id": self.user_id, "run_id": self.run_id}

    async def _emit(self, topic: str, event: str, data) -> None:
        if self.on_change is not None:
            await self.on_change(topic, event, data)

    async def ensure_indexes(self) -> None:
        await self.orders.create_index([("user_id", 1), ("id", 1)], unique=True)
        await self.fills.create_index([("user_id", 1), ("timestamp", 1)])
        await self.positions.create_index([("user_id", 1), ("symbol", 1)], unique=True)

    async def record_order(self, order: Order) -> None:
        await self.orders.insert_one(self._stamp(order.model_dump()))

    async def mark_filled(self, order_id: str) -> None:
        await self.orders.update_one(
            {"user_id": self.user_id, "id": order_id}, {"$set": {"status": "FILLED"}}
        )

    async def record_fill(self, fill: Fill) -> None:
        await self.fills.insert_one(self._stamp(fill.model_dump()))

    async def snapshot_positions(self, positions: dict[str, Position]) -> None:
        for symbol, position in positions.items():
            await self.positions.update_one(
                {"user_id": self.user_id, "symbol": symbol},
                {"$set": self._stamp(position.model_dump())},
                upsert=True,
            )
        await self._emit(
            "positions", "changed",
            {symbol: position.model_dump() for symbol, position in positions.items()},
        )

    async def get_open_positions(self, venue: Optional[Venue] = None) -> dict[str, Position]:
        cursor = self.positions.find(
            {"user_id": self.user_id, "quantity": {"$ne": 0}, **venue_filter(venue)}
        )
        docs = await cursor.to_list(length=None)
        result = {}
        for doc in docs:
            position = Position(**_clean(doc))
            result[position.symbol] = position
        return result

    async def get_fills(
        self, symbol: Optional[str] = None, since: Optional[datetime] = None,
        venue: Optional[Venue] = None,
    ) -> list[Fill]:
        query: dict = {"user_id": self.user_id, **venue_filter(venue)}
        if symbol is not None:
            query["symbol"] = symbol
        if since is not None:
            query["timestamp"] = {"$gte": since}
        cursor = self.fills.find(query).sort("timestamp", 1)
        docs = await cursor.to_list(length=None)
        return [Fill(**_clean(doc)) for doc in docs]

    # -----------------------------------------------------------------
    # Trades: the round-trip view of the same fills. A fill is one
    # execution; a trade spans from the first fill that opens a position
    # to the one that flattens it, which is what "active vs completed"
    # actually means to someone reading the dashboard.
    # -----------------------------------------------------------------

    async def on_fill(self, fill: Fill, quantity_before: float, position: Position) -> None:
        """The single call the runner makes per fill: mirrors the fill, marks
        its order filled, and advances the symbol's open trade.

        `quantity_before` is the position size before Portfolio.apply consumed
        this fill and `position` is the book afterwards -- together they say
        whether this fill opened, grew, trimmed or closed the trade, without
        this store having to re-derive the portfolio's own arithmetic.
        """
        await self.record_fill(fill)
        await self.mark_filled(fill.order_id)
        await self._advance_trade(fill, quantity_before, position)

        latest = await self.trades.find_one(
            {"user_id": self.user_id, "symbol": fill.symbol}, sort=[("entry_at", -1)]
        )
        await self._emit("trades", "changed", _clean_id(latest) if latest else {"symbol": fill.symbol})

    async def _advance_trade(self, fill: Fill, quantity_before: float, position: Position) -> None:
        open_trade = await self.trades.find_one(
            {"user_id": self.user_id, "symbol": fill.symbol, "status": "OPEN"}
        )

        if quantity_before == 0 or open_trade is None:
            await self._open_trade(fill, position)
            return

        if position.quantity == 0:
            await self.trades.update_one(
                {"_id": open_trade["_id"]},
                {"$set": {
                    "status": "CLOSED",
                    "exit_price": fill.price,
                    "exit_at": fill.timestamp,
                    "realized_pnl": position.realized_pnl,
                    "costs": open_trade.get("costs", 0.0) + fill.costs,
                }},
            )
            return

        await self.trades.update_one(
            {"_id": open_trade["_id"]},
            {"$set": {
                "quantity": abs(position.quantity),
                "entry_price": position.avg_price,
                "realized_pnl": position.realized_pnl,
                "costs": open_trade.get("costs", 0.0) + fill.costs,
            }},
        )

    async def _open_trade(self, fill: Fill, position: Position) -> None:
        order = await self.orders.find_one({"user_id": self.user_id, "id": fill.order_id})
        product = (order or {}).get("product", "MIS")

        await self.trades.insert_one(self._stamp({
            "id": str(uuid.uuid4()),
            "symbol": fill.symbol,
            "mode": "INTRADAY" if product == "MIS" else "LONGTERM",
            "side": fill.side.value if hasattr(fill.side, "value") else fill.side,
            "status": "OPEN",
            "quantity": abs(position.quantity),
            "entry_price": position.avg_price or fill.price,
            "entry_at": fill.timestamp,
            "exit_price": None,
            "exit_at": None,
            "realized_pnl": 0.0,
            "costs": fill.costs,
            "suggestion_id": (order or {}).get("suggestion_id"),
            # Which strategy's signal opened it, for the per-strategy
            # scorecard. None for an approved proposal or a pre-tag row.
            "strategy": (order or {}).get("strategy_name"),
            # A trade is paper or live for its whole life: the fill that
            # opened it decides, and closing fills never change it.
            "venue": fill.venue,
        }))

    async def get_trades(
        self, status: Optional[str] = None, limit: int = 200,
        venue: Optional[Venue] = None,
    ) -> list[dict]:
        query: dict = {"user_id": self.user_id, **venue_filter(venue)}
        if status is not None:
            query["status"] = status
        cursor = self.trades.find(query).sort("entry_at", -1).limit(limit)
        docs = await cursor.to_list(length=None)
        for doc in docs:
            doc.pop("_id", None)
        return docs

    async def get_orders(self, symbol: Optional[str] = None) -> list[Order]:
        query: dict = {"user_id": self.user_id}
        if symbol is not None:
            query["symbol"] = symbol
        cursor = self.orders.find(query)
        docs = await cursor.to_list(length=None)
        return [Order(**_clean(doc)) for doc in docs]


def venue_filter(venue: Optional[Venue]) -> dict:
    """Mongo clause for one book. Rows written before venues existed carry no
    `venue` and were all paper, so "paper" means "not live" rather than an
    exact match -- a missing tag must never leak an old row into the live book."""
    if venue is None:
        return {}
    if venue == "live":
        return {"venue": "live"}
    return {"venue": {"$ne": "live"}}


def _clean_id(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _clean(doc: dict) -> dict:
    """Strips the Mongo/ownership fields that aren't part of the core model."""
    doc = dict(doc)
    for field in ("_id", "user_id", "run_id"):
        doc.pop(field, None)
    return doc
