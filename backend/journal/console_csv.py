"""Zerodha Console tradebook CSV (Console -> Reports -> Tradebook ->
Download). Header: symbol, isin, trade_date, exchange, segment, series,
trade_type, auction, quantity, price, trade_id, order_id,
order_execution_time. `trade_type` is lowercase buy/sell;
`order_execution_time` is IST ("2024-04-01T09:15:23"). This is how history
older than today gets into the journal -- no broker's API serves it.
"""

import csv
import io

from backend.brokers.trades import parse_ist
from backend.core.models import BrokerTrade, Side

REQUIRED = {"symbol", "trade_date", "exchange", "trade_type", "quantity", "price", "trade_id"}


def parse_console_tradebook(text: str) -> tuple[list[BrokerTrade], int]:
    """Returns (trades, skipped_row_count). Raises ValueError if the header
    isn't a Console tradebook at all -- a wrong file must fail loudly, not
    import zero rows and look like success."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    fields = {f.strip().lower() for f in reader.fieldnames or []}
    missing = REQUIRED - fields
    if missing:
        raise ValueError(f"Not a Zerodha Console tradebook CSV -- missing columns: {sorted(missing)}")

    trades, skipped = [], 0
    for raw in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            when = row.get("order_execution_time") or f"{row['trade_date']} 09:15:00"
            trades.append(BrokerTrade(
                trade_id=row["trade_id"], order_id=row.get("order_id", ""),
                symbol=row["symbol"], exchange=row["exchange"] or "NSE",
                side=Side(row["trade_type"].upper()), quantity=float(row["quantity"]),
                price=float(row["price"]), traded_at=parse_ist(when),
            ))
        except (KeyError, ValueError):
            skipped += 1
    return trades, skipped
