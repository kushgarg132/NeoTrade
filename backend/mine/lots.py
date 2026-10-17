"""Tax lots of the user's own account, from the journal: still open, already
sold (realised) and reconciled with what the broker says is held. Pure
except `mine_trades`."""

from datetime import date

from backend.engine.session import IST

Lot = tuple[date, float, float]  # (IST buy date, quantity, price)
EPS = 1e-9


def _fifo(trades: list[dict], symbol: str):
    """Walks the symbol's trades oldest first; returns (matches, open lots,
    unmatched), a match being (buy_date, sell_date, qty, buy_price,
    sell_price). The part of a sell with no lot left (shares bought before
    the journal) goes to unmatched as (sell_date, qty, price)."""
    lots: list[list] = []
    matches, unmatched_ = [], []
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
        if left > EPS:
            unmatched_.append((day, left, float(t["price"])))
    return matches, [(d, q, p) for d, q, p in lots], unmatched_


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


def unmatched(trades: list[dict], symbol: str) -> list[tuple[date, float, float]]:
    """(IST sell date, qty, price) of sells the journal has no buy for."""
    return _fifo(trades, symbol)[2]


SPLIT_AVG_TOLERANCE = 0.02


def split_ratio(lots: list[Lot], broker_qty: float, broker_avg) -> int:
    """r >= 2 when the broker holds exactly r times the journal's shares at
    1/r of its average price (a split or bonus the journal never saw); else 1.
    Without the price check, shares bought before the journal look like one."""
    held = sum(q for _, q, _ in lots)
    if held <= EPS or broker_qty <= held or not broker_avg:
        return 1
    ratio = broker_qty / held
    r = round(ratio)
    journal_avg = sum(q * p for _, q, p in lots) / held
    if r >= 2 and abs(ratio - r) < 1e-6 and abs(broker_avg * r / journal_avg - 1) <= SPLIT_AVG_TOLERANCE:
        return r
    return 1


def reconcile(lots: list[Lot], broker_qty: float, broker_avg) -> tuple[list[Lot], float]:
    """(lots, unknown_qty): the journal's lots made to agree with the broker.
    A split or bonus (`split_ratio`) scales the lots; a journal short of the
    broker leaves unknown_qty bought before the journal began; a journal over
    the broker drops the oldest."""
    held = sum(q for _, q, _ in lots)
    r = split_ratio(lots, broker_qty, broker_avg)
    if r > 1:
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
    """Journal equity trades on the user's own brokers; with no roles set, all
    of them. Options and futures are left out: they are not holdings, and their
    gains are business income, not the capital gains Mine's tax page estimates."""
    from backend.brokers.roles import brokers_for
    from backend.journal.accounts import filter_trades
    from backend.journal.roundtrips import instrument_kind
    from backend.journal.store import JournalStore
    from backend.prefs import PrefsStore

    mine = brokers_for((await PrefsStore(db).get(user_id)).get("broker_roles") or {}, "mine")
    return [t for t in filter_trades(await JournalStore(db).list_trades(user_id), mine or None)
            if instrument_kind(t["symbol"], t.get("exchange")) == "STOCK"]
