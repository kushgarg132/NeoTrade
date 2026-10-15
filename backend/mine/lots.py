"""Tax lots of the user's own account, from the journal: still open, already
sold (realised) and reconciled with what the broker says is held. Pure
except `mine_trades`."""

from datetime import date

from backend.engine.session import IST

Lot = tuple[date, float, float]  # (IST buy date, quantity, price)
EPS = 1e-9


def _fifo(trades: list[dict], symbol: str):
    """Walks the symbol's trades oldest first; returns (matches, open lots),
    a match being (buy_date, sell_date, qty, buy_price, sell_price). A sell
    with no lot left (bought before the journal) is ignored."""
    lots: list[list] = []
    matches = []
    for t in sorted((t for t in trades if t["symbol"] == symbol), key=lambda t: t["traded_at"]):
        day = t["traded_at"].astimezone(IST).date()
        if t["side"] == "BUY":
            lots.append([day, float(t["quantity"]), float(t["price"])])
            continue
        left = float(t["quantity"])
        while left > EPS and lots:
            used = min(left, lots[0][1])
            matches.append((lots[0][0], day, used, lots[0][2], float(t["price"])))
            lots[0][1] -= used
            left -= used
            if lots[0][1] <= EPS:
                lots.pop(0)
    return matches, [(d, q, p) for d, q, p in lots]


def open_lots(trades: list[dict], symbol: str) -> list[Lot]:
    """(IST date, quantity, price) of the journal buys still held, oldest
    first, after sells have used up the earliest ones."""
    return _fifo(trades, symbol)[1]


def realised(trades: list[dict], symbol: str) -> list[dict]:
    """One row per FIFO match of a sell against a buy."""
    return [
        {"symbol": symbol, "buy_date": b, "sell_date": s, "qty": q, "buy_price": bp, "sell_price": sp,
         "gain": (sp - bp) * q}
        for b, s, q, bp, sp in _fifo(trades, symbol)[0]
    ]


def reconcile(lots: list[Lot], broker_qty: float) -> tuple[list[Lot], float]:
    """(lots, unknown_qty): the journal's lots made to agree with the broker.
    A whole-number ratio of 2+ is a split or bonus the journal never saw, so
    lots scale; a journal short of the broker leaves unknown_qty bought
    before the journal began; a journal over the broker drops the oldest."""
    held = sum(q for _, q, _ in lots)
    if held > EPS and broker_qty > held:
        ratio = broker_qty / held
        if round(ratio) >= 2 and abs(ratio - round(ratio)) < 1e-6:
            r = round(ratio)
            lots, held = [(d, q * r, p / r) for d, q, p in lots], broker_qty
    if held <= broker_qty + EPS:
        return list(lots), max(broker_qty - held, 0.0)
    excess, kept = held - broker_qty, []
    for d, q, p in lots:
        cut = min(excess, q)
        excess -= cut
        if q - cut > EPS:
            kept.append((d, q - cut, p))
    return kept, 0.0


async def mine_trades(db, user_id: str) -> list[dict]:
    """Journal trades on the user's own brokers; with no roles set, all of them."""
    from backend.brokers.roles import brokers_for
    from backend.journal.accounts import filter_trades
    from backend.journal.store import JournalStore
    from backend.prefs import PrefsStore

    mine = brokers_for((await PrefsStore(db).get(user_id)).get("broker_roles") or {}, "mine")
    return filter_trades(await JournalStore(db).list_trades(user_id), mine or None)
