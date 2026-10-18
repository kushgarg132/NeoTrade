"""Daily broker-to-ledger reconciliation (Phase 21, "every live trade
reconciles to the broker"). Read-only: it reads each role's broker trade
book, holdings and positions, and never places or cancels anything.

Per user and broker role (`mine`, `ai`), after the 16:00 journal sync:

- trades: the broker's own orders today vs the app's ledger fills for that
  role's book (`<uid>:mine`, `<uid>:autopilot`, matched through
  `live_orders.broker_order_id`), and each broker trade vs its journal row;
- holdings: broker holdings + positions vs the book's open quantities. The
  AI account must equal its book exactly; the user's own account may hold
  more than its book (hand trades), never less.

Kinds: `missing_in_ledger`, `missing_at_broker`, `quantity_differs`,
`price_differs`, `unknown_order` (an order on the AI account the app never
placed; hand trades on the user's own account are normal and go to the
journal only). `where` says which record disagrees: ledger, journal or
holdings.

One doc per user/day/role in `broker_reconciliation` (`_id`
"<uid>:<day>:<role>"), replaced on every run, so a re-run is idempotent. A
logged-out broker is stored as `not_checked`.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from backend.engine.persistence import LedgerStore, mine_book
from backend.engine.session import IST

logger = logging.getLogger(__name__)

COLLECTION = "broker_reconciliation"
PRICE_TOLERANCE = 0.005  # 0.5%: the ledger books the broker's own average, so more is a real difference
QTY_EPSILON = 1e-6
LABELS = {"ai": "AI account", "mine": "your account"}


def book_for(user_id: str, role: str) -> str:
    from backend.autopilot.service import ledger_user

    return mine_book(user_id) if role == "mine" else ledger_user(user_id)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _price_differs(a: float, b: float) -> bool:
    return abs(a - b) > PRICE_TOLERANCE * max(abs(a), abs(b), 1e-9)


def _mm(kind: str, where: str, symbol: str, **extra) -> dict:
    return {"kind": kind, "where": where, "symbol": symbol, **extra}


def _agg(rows) -> dict:
    """(symbol, side, quantity, price) rows -> {key: {symbol, side, qty, price}} with a VWAP price."""
    out: dict = {}
    for key, symbol, side, qty, price in rows:
        o = out.setdefault(key, {"symbol": symbol, "side": side, "qty": 0.0, "value": 0.0})
        o["qty"] += qty
        o["value"] += qty * price
    for o in out.values():
        o["price"] = o.pop("value") / o["qty"] if o["qty"] else 0.0
    return out


def _compare(kind_where: str, symbol: str, broker: dict, app: dict, **ids) -> Optional[dict]:
    if abs(broker["qty"] - app["qty"]) > QTY_EPSILON:
        return _mm("quantity_differs", kind_where, symbol, broker_qty=broker["qty"], app_qty=app["qty"], **ids)
    if _price_differs(broker["price"], app["price"]):
        return _mm("price_differs", kind_where, symbol, broker_price=round(broker["price"], 4),
                   app_price=round(app["price"], 4), **ids)
    return None


def classify(role: str, trades: list, live_rows: list[dict], fills: list, journal: dict[str, dict],
             broker_qty: dict[str, float], ledger_qty: dict[str, float]) -> list[dict]:
    """Pure. `trades` are today's BrokerTrades, `live_rows` the app's
    `live_orders` rows for this role, `fills` today's live ledger fills of the
    role's book, `journal` today's journal rows of this broker by trade id,
    `broker_qty` / `ledger_qty` open quantity per symbol."""
    out: list[dict] = []
    at_broker = _agg((t.order_id, t.symbol, t.side.value, t.quantity, t.price) for t in trades)
    booked = _agg((f.order_id, f.symbol, f.side.value, f.quantity, f.price) for f in fills)
    by_broker_id = {r["broker_order_id"]: r for r in live_rows if r.get("broker_order_id")}
    by_app_id = {r["_id"]: r for r in live_rows}

    # Trades vs the ledger.
    for broker_id, b in at_broker.items():
        row = by_broker_id.get(broker_id)
        if row is None:
            if role == "ai":
                out.append(_mm("unknown_order", "ledger", b["symbol"], broker_order_id=broker_id,
                               side=b["side"], broker_qty=b["qty"]))
            continue
        app = booked.get(row["_id"])
        if app is None:
            out.append(_mm("missing_in_ledger", "ledger", b["symbol"], broker_order_id=broker_id,
                           side=b["side"], broker_qty=b["qty"]))
        elif mm := _compare("ledger", b["symbol"], b, app, broker_order_id=broker_id):
            out.append(mm)
    for app_id, app in booked.items():
        row = by_app_id.get(app_id)
        if row is None or row.get("broker_order_id") not in at_broker:
            out.append(_mm("missing_at_broker", "ledger", app["symbol"], order_id=app_id,
                           side=app["side"], app_qty=app["qty"]))

    # Trades vs the journal (the 16:00 sync just ran).
    trade_ids = set()
    for t in trades:
        trade_ids.add(t.trade_id)
        row = journal.get(t.trade_id)
        if row is None:
            out.append(_mm("missing_in_ledger", "journal", t.symbol, trade_id=t.trade_id, broker_qty=t.quantity))
        elif mm := _compare("journal", t.symbol, {"qty": t.quantity, "price": t.price},
                            {"qty": float(row["quantity"]), "price": float(row["price"])}, trade_id=t.trade_id):
            out.append(mm)
    for trade_id, row in journal.items():
        if trade_id not in trade_ids:
            out.append(_mm("missing_at_broker", "journal", row["symbol"], trade_id=trade_id,
                           app_qty=float(row["quantity"])))

    # Holdings + positions vs the book's open quantities.
    symbols = set(ledger_qty) | (set(broker_qty) if role == "ai" else set())
    for symbol in sorted(symbols):
        b, a = broker_qty.get(symbol, 0.0), ledger_qty.get(symbol, 0.0)
        if role == "mine" and b + QTY_EPSILON >= a:
            continue  # the user's own account may hold more than the app placed
        if abs(b - a) <= QTY_EPSILON:
            continue
        kind = "missing_at_broker" if abs(b) <= QTY_EPSILON else "missing_in_ledger" if abs(a) <= QTY_EPSILON \
            else "quantity_differs"
        out.append(_mm(kind, "holdings", symbol, broker_qty=b, app_qty=a))
    return out


def _bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tzinfo=IST)
    return start, start + timedelta(days=1)


async def _broker_quantities(adapter) -> dict[str, float]:
    # ponytail: holdings + today's positions. A same-day CNC sell can read as a
    # difference on a broker whose holdings still count the sold shares until
    # settlement; the next day's run clears it.
    qty: dict[str, float] = defaultdict(float)
    for h in await adapter.get_holdings():
        if h.kind != "MF":
            qty[h.symbol] += h.quantity
    for symbol, p in (await adapter.get_positions()).items():
        qty[symbol] += p.quantity
    return {s: q for s, q in qty.items() if abs(q) > QTY_EPSILON}


async def check_role(db, user_id: str, role: str, broker: str, adapter, day: date) -> dict:
    """Mismatches for one role's broker on `day`."""
    start, end = _bounds(day)
    book = book_for(user_id, role)
    ledger = LedgerStore(db, user_id=book)
    fills = [f for f in await ledger.get_fills(since=start, venue="live") if _aware(f.timestamp) < end]
    fill_ids = sorted({f.order_id for f in fills})
    live_rows = await db["live_orders"].find({"user_id": user_id, "role": role, "$or": [
        {"submitted_at": {"$gte": start, "$lt": end}}, {"_id": {"$in": fill_ids}}]}).to_list(length=None)
    journal = {}
    async for row in db["journal_trades"].find({"user_id": user_id, "broker": broker,
                                                "traded_at": {"$gte": start, "$lt": end}}):
        journal[row["trade_id"]] = row
    trades = [t for t in await adapter.get_trades() if start <= _aware(t.traded_at) < end]
    ledger_qty = {s: p.quantity for s, p in (await ledger.get_open_positions(venue="live")).items()}
    mismatches = classify(role, trades, live_rows, fills, journal, await _broker_quantities(adapter), ledger_qty)
    return {"mismatches": mismatches,
            "counts": {"broker_trades": len(trades), "ledger_fills": len(fills), "journal_trades": len(journal),
                       "open_symbols": len(ledger_qty)}}


async def _store(db, user_id: str, day: date, role: str, broker: Optional[str], now: datetime, **body) -> dict:
    doc = {"_id": f"{user_id}:{day.isoformat()}:{role}", "user_id": user_id, "day": day.isoformat(),
           "role": role, "broker": broker, "checked_at": now, "mismatches": [], "reason": None, **body}
    doc["status"] = body.get("status") or ("mismatch" if doc["mismatches"] else "ok")
    await db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return doc


async def ensure_indexes(db) -> None:
    try:
        await db[COLLECTION].create_index([("user_id", 1), ("day", -1)])
    except Exception as exc:  # the run must not fail on it
        logger.error("broker_reconciliation index not created: %s", exc)


async def reconcile_user(db, user_id: str, roles: dict, get_adapter, day: date, now: datetime) -> list[dict]:
    """`get_adapter(broker)` -> that broker's adapter for this user."""
    from backend.brokers.protocol import BrokerSessionState
    from backend.brokers.roles import FILE_SOURCES, ROLES, brokers_for

    docs = []
    for role in ROLES:
        brokers = sorted(brokers_for(roles, role) - FILE_SOURCES)
        if not brokers:
            continue  # no broker has this role: nothing to reconcile
        # ponytail: the first logged-in broker of the role, the one orders route to
        # (roles.py::adapter_for); a second `mine` broker is not compared.
        chosen = None
        for broker in brokers:
            adapter = await get_adapter(broker)
            if await adapter.state() == BrokerSessionState.ACTIVE:
                chosen = (broker, adapter)
                break
        if chosen is None:
            docs.append(await _store(db, user_id, day, role, brokers[0], now, status="not_checked",
                                     reason="not checked: logged out"))
            continue
        try:
            result = await check_role(db, user_id, role, chosen[0], chosen[1], day)
        except Exception as exc:
            logger.warning("broker reconciliation failed for %s/%s: %s", user_id, role, exc)
            docs.append(await _store(db, user_id, day, role, chosen[0], now, status="not_checked",
                                     reason=f"not checked: broker error ({type(exc).__name__})"))
            continue
        docs.append(await _store(db, user_id, day, role, chosen[0], now, **result))
    return docs


async def run_all(db, redis, day: date, now: datetime) -> int:
    """Every user with broker roles. Returns how many role docs have mismatches."""
    from backend.auth.broker_credentials import BrokerCredentialStore, fernet_from_settings
    from backend.brokers.registry import get_broker_adapter

    await ensure_indexes(db)
    credentials = BrokerCredentialStore(db, fernet_from_settings())
    found = 0
    async for prefs in db["user_prefs"].find({"broker_roles": {"$exists": True, "$ne": {}}},
                                              {"user_id": 1, "broker_roles": 1}):
        user_id = prefs["user_id"]

        async def get_adapter(broker, user_id=user_id):
            return await get_broker_adapter(broker, user_id, credentials, redis)

        try:
            docs = await reconcile_user(db, user_id, prefs["broker_roles"], get_adapter, day, now)
        except Exception as exc:
            logger.exception("broker reconciliation failed for %s: %s", user_id, exc)
            continue
        found += sum(d["status"] == "mismatch" for d in docs)
    return found


async def latest(db, user_id: str, since: Optional[date] = None) -> list[dict]:
    """The user's most recent day of results (on or after `since`), one doc per role."""
    newest = await db[COLLECTION].find_one({"user_id": user_id}, {"day": 1}, sort=[("day", -1)])
    if not newest or (since and newest["day"] < since.isoformat()):
        return []
    return await db[COLLECTION].find({"user_id": user_id, "day": newest["day"]}).sort("role", 1).to_list(length=None)


def summary(docs: list[dict]) -> Optional[str]:
    """"AI account: 2 (ITC, TCS)" per role that disagrees, or None."""
    bad = [d for d in docs if d["status"] == "mismatch"]
    if not bad:
        return None
    parts = []
    for d in bad:
        symbols = sorted({m["symbol"] for m in d["mismatches"]})
        more = f" +{len(symbols) - 3}" if len(symbols) > 3 else ""
        parts.append(f"{LABELS.get(d['role'], d['role'])}: {len(d['mismatches'])} ({', '.join(symbols[:3])}{more})")
    return "; ".join(parts)
