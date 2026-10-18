"""The journal split by account: the AI's (role "ai") and the user's own
("mine"), see backend/brokers/roles.py. Pure, no I/O."""

from datetime import date
from typing import Optional

from backend.brokers.roles import brokers_for
from backend.engine.session import IST
from backend.journal import mirror
from backend.journal.roundtrips import build_round_trips


def filter_trades(trades: list[dict], brokers: Optional[set[str]]) -> list[dict]:
    """None means every account."""
    return trades if brokers is None else [t for t in trades if t.get("broker") in brokers]


def brokers_of(roles: dict, account: str) -> Optional[set[str]]:
    return None if account == "all" else brokers_for(roles, account)


def ai_vs_me(trades: list[dict], roles: dict, capital_by_role: dict, nifty: list) -> list[dict]:
    """Per calendar month (IST): each account's P&L before and after estimated
    charges, return on its capital, fills -- and the Nifty's return."""
    def month_of(at) -> str:
        return at.astimezone(IST).strftime("%Y-%m")

    # Round trips over each account's whole history, then bucketed by the
    # month they closed: built per month, a January buy and a February sell
    # were two open halves and their P&L vanished (HINDCOPPER, SILVERBEES).
    books = {}
    for role in ("ai", "mine"):
        brokers = brokers_for(roles, role)
        if role == "mine" and not brokers:  # no roles set: every non-AI broker is mine, as elsewhere
            fills = [t for t in trades if t.get("broker") not in brokers_for(roles, "ai")]
        else:
            fills = filter_trades(trades, brokers)
        books[role] = (fills, build_round_trips(fills))
    rows = []
    for month in sorted({month_of(t["traded_at"]) for t in trades}):
        row = {"month": month}
        for role, (fills, trips) in books.items():
            closed = [trip for trip in trips if trip.get("closed_at") and month_of(trip["closed_at"]) == month]
            costs = mirror.costs([t for t in fills if month_of(t["traded_at"]) == month], closed,
                                 capital_by_role.get(role) or 0)
            capital = capital_by_role.get(role) or 0
            row[role] = {"gross_pnl": costs["gross_pnl"], "net_pnl": costs["net_pnl"], "charges": costs["charges"],
                         "fills": costs["fills"], "return": costs["net_pnl"] / capital if capital else None}
        year, mon = map(int, month.split("-"))
        window = [c for d, c in nifty if (d.year, d.month) == (year, mon)]
        row["nifty_return"] = window[-1] / window[0] - 1 if len(window) >= 2 else None
        rows.append(row)
    return rows
