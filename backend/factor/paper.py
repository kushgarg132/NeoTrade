"""The factor portfolio on paper: one book per user, rebalanced at the first
morning pass of each month (backend/engine/autorun.py).

The book (collection `factor_books`) is its own paper allocation,
`factor_paper_capital` (default ₹3 lakh), apart from the user's account
size -- the strategy needs that much to hold its names in whole shares.
It records shares and cash exactly; every trade is also booked through
the normal paper ledger (service.fill_on_paper) so it shows in the app.

Decisions use closes through the last session and trade at the live mark,
as the backtest decides on a close and trades the next day. The risk-off
sleeve is modelled as cash earning a liquid ETF's yield, as in the
backtest (LIQUIDBEES has no mark in the instrument master).
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.core.models import Order, Side
from backend.engine.execution.costs import calculate_indian_costs
from backend.engine.persistence import LedgerStore
from backend.factor import data, model
from backend.factor.backtest import RISK_OFF_YIELD
from backend.factor.model import Params
from backend.marks import mark_prices
from backend.prefs import PrefsStore
from backend.suggestions.service import fill_on_paper

logger = logging.getLogger(__name__)

STRATEGY = "factor_momentum_lowvol"
# The variant the walk-forward chose in most recent years (python -m backend.factor.report).
PARAMS = Params(momentum_weight=1.0, top_n=15, buffer=25, target_vol=0.15)


def _load() -> tuple:
    return data.closes(data.universe()), data.series(data.MARKET)


class FactorBookStore:
    def __init__(self, db):
        self.collection = db["factor_books"]

    async def get(self, user_id: str) -> Optional[dict]:
        return await self.collection.find_one({"_id": user_id})

    async def save(self, user_id: str, book: dict) -> None:
        await self.collection.replace_one({"_id": user_id}, {**book, "_id": user_id, "user_id": user_id}, upsert=True)


async def due(db, user_id: str, now: datetime) -> bool:
    """No book yet, or not rebalanced in this calendar month."""
    book = await FactorBookStore(db).get(user_id)
    if not book or not book.get("last_rebalance"):
        return True
    last = book["last_rebalance"]
    return (last.year, last.month) != (now.year, now.month)


def _accrue(book: dict, now: datetime) -> None:
    """Idle cash earns the risk-off sleeve's yield since the book last moved."""
    since = book.get("updated_at")
    if since:
        since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        days = max((now - since).days, 0)
        book["cash"] *= (1 + RISK_OFF_YIELD) ** (days / 365)


async def rebalance(db, user_id: str, now: Optional[datetime] = None, marks_fn=mark_prices,
                    load=None) -> dict:
    """Trades the book to this month's target. Returns a summary for the
    morning message: exposure, what was bought and sold, equity."""
    from backend.profile.store import ProfileStore
    from backend.ws.publish import publisher_for

    now = now or datetime.now(timezone.utc)
    store = FactorBookStore(db)
    prefs = await PrefsStore(db).get(user_id)
    capital = float(prefs["factor_paper_capital"])
    book = await store.get(user_id) or {"cash": capital, "shares": {}, "start_equity": capital}
    book.pop("_id", None)
    _accrue(book, now)

    closes, market = await asyncio.to_thread(load or _load)
    avoid = set((await ProfileStore(db).get(user_id)).get("avoid") or [])
    t = closes.index[-1]
    nifty = float(market.dropna().iloc[-1])
    book.setdefault("started_at", now)
    book.setdefault("start_nifty", nifty)
    target, level = model.target_book(closes, market, t, set(book["shares"]), PARAMS, avoid=avoid)

    marks = await marks_fn(db, set(target.index) | set(book["shares"]))
    held_value = sum(q * marks.get(s, 0.0) for s, q in book["shares"].items())
    equity = book["cash"] + held_value
    want = {s: int(w * equity // marks[s]) for s, w in target.items() if marks.get(s)}
    orders = {s: want.get(s, 0) - q for s, q in book["shares"].items() if marks.get(s)}
    orders.update({s: q for s, q in want.items() if s not in book["shares"]})

    ledger = LedgerStore(db, user_id=user_id, on_change=publisher_for(user_id))
    bought, sold = [], []
    for symbol, delta in sorted(orders.items(), key=lambda kv: kv[1]):  # sells first
        price = marks[symbol]
        quantity = abs(delta)
        if delta > 0:
            quantity = min(quantity, int(book["cash"] // (price * 1.003)))  # never borrow
        if quantity <= 0:
            continue
        side = Side.BUY if delta > 0 else Side.SELL
        order = Order(id=str(uuid.uuid4()), symbol=symbol, side=side, quantity=quantity, order_type="MARKET",
                      limit_price=None, product="CNC", strategy_name=STRATEGY)
        try:
            await fill_on_paper(ledger, order, price, now)
        except Exception as exc:
            logger.exception("factor %s of %s failed for %s: %s", side.value, symbol, user_id, exc)
            continue
        value = price * quantity
        costs = calculate_indian_costs(price, quantity, side, "CNC")
        book["cash"] += (-value if side == Side.BUY else value) - costs
        book["costs"] = book.get("costs", 0.0) + costs
        book["shares"][symbol] = book["shares"].get(symbol, 0) + (quantity if side == Side.BUY else -quantity)
        if book["shares"][symbol] == 0:
            del book["shares"][symbol]
        (bought if side == Side.BUY else sold).append({"symbol": symbol, "quantity": quantity, "price": price})

    held_value = sum(q * marks.get(s, 0.0) for s, q in book["shares"].items())
    summary = {"date": now.isoformat(), "exposure": round(level, 3), "decided_on": str(t.date()),
               "bought": bought, "sold": sold, "equity": round(book["cash"] + held_value, 2),
               "invested": round(held_value, 2),
               # The live gate's yardstick: the book vs holding the Nifty since it started.
               "book_return": (book["cash"] + held_value) / book.get("start_equity", capital) - 1,
               "nifty_return": nifty / book["start_nifty"] - 1}
    book.update(last_rebalance=now, updated_at=now, last_summary=summary)
    await store.save(user_id, book)
    logger.info("factor rebalance for %s: exposure %.2f, %d buys, %d sells", user_id, level, len(bought), len(sold))
    return summary


def summary_text(summary: dict) -> str:
    lines = [f"Monthly rebalance of your factor portfolio (paper) — equity ₹{summary['equity']:,.0f}, "
             f"{summary.get('book_return', 0):+.1%} since it started vs Nifty {summary.get('nifty_return', 0):+.1%}."]
    if summary["exposure"] == 0:
        lines.append("The Nifty is below its 200-day average: the portfolio is in the risk-off sleeve (liquid ETF).")
    else:
        lines.append(f"In stocks: {summary['exposure']:.0%} of the book (vol-targeted).")
    for label, rows in (("Bought", summary["bought"]), ("Sold", summary["sold"])):
        if rows:
            lines.append(f"{label}: " + ", ".join(f"{r['symbol']} ×{r['quantity']}" for r in rows))
    return "\n".join(lines)
