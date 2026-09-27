"""Kite Connect order operations. Real pykiteconnect API surface used
(verified against the installed SDK's place_order/cancel_order/
order_history/positions signatures, and https://kite.trade/docs/connect/v3/
orders/ + .../portfolio/, fetched live 2026-09-09):

- `place_order(variety, exchange, tradingsymbol, transaction_type, quantity,
  product, order_type, price=None, ...)` -> the SDK returns the order id
  string directly (not the raw `{"data": {"order_id": ...}}` envelope).
- `cancel_order(variety, order_id, parent_order_id=None)`.
- `order_history(order_id)` -> list of dicts, one per state transition; the
  last element is the current state. `status` values per Kite's docs:
  COMPLETE, REJECTED, CANCELLED, OPEN, TRIGGER PENDING, OPEN PENDING,
  VALIDATION PENDING, MODIFY PENDING, MODIFY VALIDATION PENDING, CANCEL
  PENDING, AMO REQ RECEIVED, MODIFIED, PUT ORDER REQ RECEIVED -- anything
  not COMPLETE/REJECTED/CANCELLED maps to PARTIALLY_FILLED (if
  filled_quantity > 0) or ACKNOWLEDGED (a live account has never
  exercised this mapping; verified against docs only, same posture as
  every other broker adapter in this codebase).
- `positions()` -> {"net": [...], "day": [...]} directly (SDK unwraps the
  data envelope, same as KiteProvider.quote already relies on).
- `holdings()` / `mf_holdings()` -> equity and mutual fund holdings. Field
  names checked against Zerodha's own kiteconnect-mocks responses
  (holdings.json, mf_holdings.json on GitHub, 2026-09-27): quantity is
  settled shares, t1_quantity those still settling; MF rows carry the fund
  name in `fund` and the ISIN in `tradingsymbol`.
- `trades()` -> list of today's fills: trade_id, order_id, exchange,
  tradingsymbol, transaction_type, quantity, average_price, fill_timestamp
  (the SDK parses 19-char timestamps into naive IST datetimes itself).

An option order carries its NFO contract (Order.contract): Kite takes the
same tradingsymbol with exchange="NFO", product NRML or MIS (Kite's order
docs list NFO among the exchanges and NRML as the F&O carry-forward
product). The contract list itself is Kite's own dump, so the symbol is
Kite's format already.

Only MARKET orders are placed here -- LIMIT order price handling is out of
scope (see docs/superpowers/specs/2026-09-09-live-equity-execution-design.md).
"""

import asyncio
from typing import Callable

from backend.brokers.holdings import kind_of
from backend.brokers.trades import parse_ist
from backend.core.models import BrokerOrderStatus, BrokerTrade, Holding, Order, Position, Side


class KiteOrderClient:
    def __init__(self, kite_client_factory: Callable[[], "KiteConnect"]) -> None:  # noqa: F821
        self._kite_client_factory = kite_client_factory

    async def place_order(self, order: Order) -> str:
        kite = self._kite_client_factory()
        return await asyncio.to_thread(
            kite.place_order,
            variety="regular",
            exchange=order.contract.exchange if order.contract is not None else "NSE",
            tradingsymbol=order.symbol,
            transaction_type=order.side.value,
            quantity=order.whole_quantity(),
            product=order.product,
            order_type=order.order_type,
        )

    async def cancel_order(self, broker_order_id: str) -> None:
        kite = self._kite_client_factory()
        await asyncio.to_thread(kite.cancel_order, variety="regular", order_id=broker_order_id)

    @staticmethod
    def _map_status(raw_status: str, filled_quantity: float) -> str:
        if raw_status == "COMPLETE":
            return "FILLED"
        if raw_status == "REJECTED":
            return "REJECTED"
        if raw_status == "CANCELLED":
            return "CANCELLED"
        return "PARTIALLY_FILLED" if filled_quantity > 0 else "ACKNOWLEDGED"

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        kite = self._kite_client_factory()
        history = await asyncio.to_thread(kite.order_history, broker_order_id)
        latest = history[-1]
        return BrokerOrderStatus(
            broker_order_id=broker_order_id,
            status=self._map_status(latest["status"], latest["filled_quantity"]),
            filled_quantity=float(latest["filled_quantity"]),
            average_price=float(latest["average_price"]),
        )

    async def get_positions(self) -> dict[str, Position]:
        kite = self._kite_client_factory()
        data = await asyncio.to_thread(kite.positions)
        return {
            row["tradingsymbol"]: Position(
                symbol=row["tradingsymbol"],
                quantity=float(row["quantity"]),
                avg_price=float(row["average_price"]),
                realized_pnl=float(row.get("realised", 0.0)),
                unrealized_pnl=float(row.get("unrealised", 0.0)),
                exchange=row.get("exchange"),
                product=row.get("product"),
            )
            for row in data["net"]
        }

    async def get_trades(self) -> list[BrokerTrade]:
        kite = self._kite_client_factory()
        rows = await asyncio.to_thread(kite.trades)
        return [
            BrokerTrade(
                trade_id=str(row["trade_id"]), order_id=str(row.get("order_id", "")),
                symbol=row["tradingsymbol"], exchange=row.get("exchange", "NSE"),
                side=Side(row["transaction_type"]), quantity=float(row["quantity"]),
                price=float(row["average_price"]),
                traded_at=parse_ist(row.get("fill_timestamp") or row["exchange_timestamp"]),
            )
            for row in rows
        ]

    async def get_holdings(self) -> list[Holding]:
        kite = self._kite_client_factory()
        stocks = await asyncio.to_thread(kite.holdings)
        funds = await asyncio.to_thread(kite.mf_holdings)
        result = [
            Holding(
                symbol=row["tradingsymbol"], isin=row.get("isin"), exchange=row.get("exchange"),
                kind=kind_of(row["tradingsymbol"]),
                quantity=float(row.get("quantity") or 0) + float(row.get("t1_quantity") or 0),
                avg_price=float(row.get("average_price") or 0),
                last_price=row.get("last_price") or None, close_price=row.get("close_price") or None,
                broker="kite",
            )
            for row in stocks
        ]
        result += [
            Holding(
                symbol=row["tradingsymbol"], isin=row["tradingsymbol"], name=row.get("fund"), kind="MF",
                quantity=float(row.get("quantity") or 0), avg_price=float(row.get("average_price") or 0),
                last_price=row.get("last_price") or None, broker="kite",
            )
            for row in funds
        ]
        return [h for h in result if h.quantity > 0]
