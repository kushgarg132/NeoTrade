"""Mutual funds from a CAMS/KFintech CAS PDF (casparser, parsed in memory).

The PDF and its password are never stored or logged: only the parsed funds
and transactions are, per user, in `mf_imports` (one doc per user = the
holdings, shaped like a broker's MF `Holding` with broker="cas") and
`mf_transactions`. A new upload replaces the last one (a CAS is the full
statement). Portfolio refresh reads the holdings back (`portfolio.service.
fetch_holdings`). Not in mine/lots or mine/tax: those are built from stock
trades; MF capital gains are a separate design.
"""

import io
from datetime import date, datetime, timezone

CAS_BROKER = "cas"
MAX_BYTES = 10 * 1024 * 1024


class CasError(ValueError):
    """Safe to show the user: never carries the file's content or password."""


def _read(data: bytes, password: str):
    import casparser

    return casparser.read_cas_pdf(io.BytesIO(data), password)


def parse_cas(data: bytes, password: str) -> tuple[list[dict], list[dict], dict]:
    """(holdings, transactions, period) from the PDF bytes."""
    if len(data) > MAX_BYTES:
        raise CasError("That file is over 10 MB.")
    if not data.startswith(b"%PDF"):
        raise CasError("That is not a PDF.")
    try:
        cas = _read(data, password)
    except Exception as exc:  # the message may quote the file: map by type only
        if type(exc).__name__ == "IncorrectPasswordError":
            raise CasError("Wrong password. For CAMS/KFintech it is the one you set when requesting the statement.")
        raise CasError("Could not read this as a CAMS or KFintech statement.")
    if not hasattr(cas, "folios"):
        raise CasError("This looks like an NSDL/CDSL statement. Upload the CAMS or KFintech mutual fund CAS.")
    return from_cas(cas)


def _f(value) -> float | None:
    return None if value is None else float(value)


def _day(value) -> str:
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


def from_cas(cas) -> tuple[list[dict], list[dict], dict]:
    held: dict[str, dict] = {}
    txns: list[dict] = []
    for folio in cas.folios:
        for scheme in folio.schemes:
            isin = scheme.isin or scheme.amfi or scheme.scheme
            units = float(scheme.close)
            for t in scheme.transactions:
                txns.append({
                    "folio": folio.folio, "isin": isin, "scheme": scheme.scheme, "date": _day(t.date),
                    "type": getattr(t.type, "value", str(t.type)), "units": _f(t.units),
                    "nav": _f(t.nav), "amount": _f(t.amount),
                })
            if units <= 0:
                continue
            val = scheme.valuation
            # The statement's own cost; with none, cost = today's value (no gain is claimed).
            cost = float(val.cost) if val.cost else float(val.value)
            row = held.setdefault(isin, {
                "symbol": isin, "isin": isin, "name": scheme.scheme, "exchange": None, "kind": "MF",
                "quantity": 0.0, "avg_price": 0.0, "last_price": float(val.nav), "close_price": None,
                "broker": CAS_BROKER, "_cost": 0.0,
            })
            row["quantity"] += units
            row["_cost"] += cost
    holdings = []
    for row in held.values():
        row["avg_price"] = row.pop("_cost") / row["quantity"]
        holdings.append(row)
    period = cas.statement_period
    return holdings, txns, {"from": str(period.from_), "to": str(period.to)}


async def save(db, user_id: str, holdings: list[dict], txns: list[dict], period: dict) -> None:
    await db["mf_imports"].replace_one(
        {"_id": user_id},
        {"_id": user_id, "user_id": user_id, "holdings": holdings, "period": period,
         "imported_at": datetime.now(timezone.utc)},
        upsert=True,
    )
    await db["mf_transactions"].delete_many({"user_id": user_id})
    if txns:
        await db["mf_transactions"].insert_many(
            [{"_id": f"{user_id}:{i}", "user_id": user_id, **t} for i, t in enumerate(txns)])


async def holdings_of(db, user_id: str) -> list[dict]:
    doc = await db["mf_imports"].find_one({"_id": user_id})
    return (doc or {}).get("holdings") or []


async def status(db, user_id: str) -> dict:
    doc = await db["mf_imports"].find_one({"_id": user_id}) or {}
    return {
        "funds": len(doc.get("holdings") or []), "period": doc.get("period"), "imported_at": doc.get("imported_at"),
        "transactions": await db["mf_transactions"].count_documents({"user_id": user_id}),
        "trades": await db["journal_trades"].count_documents({"user_id": user_id, "source": "console_csv"}),
    }


async def delete_imported(db, user_id: str) -> dict:
    """Everything this user uploaded: CAS funds and transactions, and the
    fills that came from a Console CSV (broker-synced fills stay)."""
    await db["mf_imports"].delete_one({"_id": user_id})
    txns = await db["mf_transactions"].delete_many({"user_id": user_id})
    trades = await db["journal_trades"].delete_many({"user_id": user_id, "source": "console_csv"})
    return {"transactions": txns.deleted_count, "trades": trades.deleted_count}
