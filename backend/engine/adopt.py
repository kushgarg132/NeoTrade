"""What a new intraday run inherits. A restart (every deploy) used to start
each run from an empty portfolio, so open intraday positions were forgotten:
never squared off, invisible to the per-stock cap, exposure and the kill
switch. Today's open intraday trades are adopted with the strategy that owns
them; older ones (an intraday position cannot outlive its day) are closed at
their mark. Time is passed in: this module must not read the clock itself.
"""

import logging
import uuid
from datetime import datetime, time as dt_time, timezone
from typing import Awaitable, Callable

from backend.core.models import Order, Position, Side
from backend.engine.persistence import LedgerStore, trade_net
from backend.engine.runner import level_for
from backend.engine.session import IST
from backend.suggestions.service import fill_on_paper

logger = logging.getLogger(__name__)


def _day(value: datetime):
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(IST).date()


async def adopt_intraday(db, user_id: str, now: datetime) -> tuple[dict[str, Position], dict[str, str], list[dict], dict[str, dict]]:
    """(positions, holders, stale, levels): today's open intraday paper trades as
    positions plus their owning strategy and exit levels (rebuilt from the
    latest trade's stored context; none without a stop); earlier days' as
    trades to close."""
    open_trades = await db["paper_trades"].find(
        # The autopilot's MIS trades in this book are its own to square off.
        {"user_id": user_id, "mode": "INTRADAY", "status": "OPEN", "venue": {"$in": ["paper", None]},
         "via": {"$not": {"$regex": "^autopilot:"}}}
    ).to_list(length=None)
    today = now.astimezone(IST).date()
    stale, by_symbol = [], {}
    for trade in open_trades:
        if _day(trade["entry_at"]) != today:
            stale.append(trade)
        else:
            by_symbol.setdefault(trade["symbol"], []).append(trade)

    # A stock can carry several open trades (runs that started empty opened a
    # fresh one for a stock already held): net them into one position.
    positions, holders, levels = {}, {}, {}
    for symbol, trades in by_symbol.items():
        signed = [(1 if t["side"] == "BUY" else -1) * float(t["quantity"]) for t in trades]
        net = sum(signed)
        if net == 0:
            continue
        same_way = [(q, float(t["entry_price"])) for q, t in zip(signed, trades) if (q > 0) == (net > 0)]
        avg = sum(abs(q) * p for q, p in same_way) / sum(abs(q) for q, _ in same_way)
        # The trade the next fill advances (LedgerStore._advance_trade: the first
        # open one on the held side) books position.realized_pnl - realized_base:
        # seed what it had realized on top of its base, or its close loses both.
        first = next(t for q, t in zip(signed, trades) if (q > 0) == (net > 0))
        realized = float(first.get("realized_base") or 0.0) + float(first.get("realized_pnl") or 0.0)
        positions[symbol] = Position(symbol=symbol, quantity=net, avg_price=avg, realized_pnl=realized)
        latest = max(trades, key=lambda t: t["entry_at"])
        if latest.get("strategy"):
            holders[symbol] = latest["strategy"]
        seed = level_for(Order(id="adopted", symbol=symbol, side=Side.BUY, quantity=1, order_type="MARKET",
                               product="MIS", context=latest.get("context")), None)
        if seed:
            levels[symbol] = {**seed, "fresh": False}
    return positions, holders, stale, levels


async def option_legs(master, adopted: dict[str, Position], holders: dict[str, str],
                      levels: dict[str, dict], now: datetime) -> dict[str, dict]:
    """Adopted bought options as the runner's `option_legs`, so a restart keeps
    their stop / target (levels on the underlying, from the trade's context)
    and the 15:15 square-off. The equity `levels` entry for such a symbol is
    dropped. Without a stored level only the square-off applies."""
    legs = {}
    for symbol, position in adopted.items():
        if position.quantity <= 0 or (contract := await master.get("NFO", symbol)) is None:
            continue
        if contract.instrument_type not in ("CE", "PE"):
            continue
        bullish = contract.instrument_type == "CE"
        lv = levels.pop(symbol, None) or {}
        never = float("-inf") if bullish else float("inf")
        legs[symbol] = {
            "underlying": contract.name, "day": now.astimezone(IST).date(), "contract": contract,
            "bullish": bullish, "stop": lv.get("stop") if lv.get("stop") is not None else never,
            "target": lv.get("target") if lv.get("target") is not None else -never,
            "mark": position.avg_price, "strategy_name": holders.get(symbol),
        }
    return legs


async def booked_today(ledger: LedgerStore, now: datetime, adopted: dict[str, Position]) -> float:
    """What earlier intraday runs booked today (net), so a restart does not
    re-arm the loss limit: today's INTRADAY trades only, not a long-term exit
    and not an earlier day's position close_stale just closed (opened before
    today). The realized P&L seeded into adopted positions is taken off: the
    portfolio counts it again (Portfolio.equity), and its base is already in
    today's closed trades."""
    day_start = datetime.combine(now.astimezone(IST).date(), dt_time(0, 0), tzinfo=IST)
    booked = sum(
        trade_net(t)
        for t in await ledger.get_trades(status="CLOSED", venue="paper", mode="INTRADAY", limit=2000)
        if t.get("exit_at") and t["exit_at"] >= day_start and t["entry_at"] >= day_start
        and not (t.get("via") or "").startswith("autopilot:")
    )
    return booked - sum(p.realized_pnl for p in adopted.values())


async def close_stale(
    ledger: LedgerStore, stale: list[dict], mark_price: Callable[[str], Awaitable[float]], now: datetime,
) -> int:
    """Closes each stale intraday trade at its mark; one without a price is
    left for the next run start. Returns how many were closed."""
    closed = 0
    for trade in stale:
        try:
            price = await mark_price(trade["symbol"])
        except Exception as exc:
            logger.warning("stale intraday %s not closed this time: %s", trade["symbol"], exc)
            continue
        order = Order(
            id=str(uuid.uuid4()), symbol=trade["symbol"],
            side=Side.SELL if trade["side"] == "BUY" else Side.BUY,
            quantity=float(trade["quantity"]), order_type="MARKET", product="MIS",
            strategy_name=trade.get("strategy"),
        )
        await fill_on_paper(ledger, order, price, now)
        logger.info("closed stale intraday %s %s at %.2f", trade["symbol"], trade["side"], price)
        closed += 1
    return closed
