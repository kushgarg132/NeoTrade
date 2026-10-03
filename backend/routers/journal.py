"""/journal/* -- the user's real broker trades, grouped into round trips,
with a daily P&L calendar and their own notes and tags. Everything here is
the user's own data about their own trading: nothing is a recommendation.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.broker_credentials import BrokerCredentialStore, get_credential_store
from backend.auth.dependency import get_current_user, require_admin
from backend.auth.models import User
from backend.database import db
from backend.journal.beta import beta_metrics, record_open
from backend.journal.console_csv import parse_console_tradebook
from backend.journal.insights import build_insights
from backend.journal.roundtrips import build_round_trips, daily_pnl
from backend.journal.store import JournalStore
from backend.journal.sync import connected_brokers, import_upstox_history, sync_user_trades

router = APIRouter(prefix="/journal", tags=["Journal"])

MAX_CSV_BYTES = 10 * 1024 * 1024


def get_journal_store() -> JournalStore:
    return JournalStore(db.db)


class ImportRequest(BaseModel):
    csv: str = Field(max_length=MAX_CSV_BYTES)


class HistoryRequest(BaseModel):
    days: int = Field(default=365, ge=1, le=730)


class NoteRequest(BaseModel):
    note: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)


@router.get("")
async def get_journal(
    user: User = Depends(get_current_user), store: JournalStore = Depends(get_journal_store),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    await record_open(db.db, user.id)
    trips = build_round_trips(await store.list_trades(user.id))
    notes = await store.notes_for(user.id)
    for trip in trips:
        trip.update(notes.get(trip["id"], {"note": "", "tags": []}))
    trips.reverse()  # newest first for the list view
    closed = [t for t in trips if t["pnl"] is not None]
    return {
        "round_trips": trips,
        "calendar": daily_pnl(trips),
        "insights": build_insights(trips),
        # So an empty journal can say "connected, nothing imported yet"
        # rather than "connect a broker".
        "brokers_connected": await connected_brokers(db.redis, credentials, user.id),
        "summary": {
            "trips": len(closed),
            "pnl": round(sum(t["pnl"] for t in closed), 2),
            "wins": sum(t["pnl"] > 0 for t in closed),
            "by_kind": _by_kind(closed),
        },
    }


def _by_kind(closed: list[dict]) -> dict:
    """Stocks, options and futures kept apart: an options habit can sink an
    otherwise sound stock book, and the total hides which."""
    groups: dict[str, dict] = {}
    for trip in closed:
        label = {"CALL": "options", "PUT": "options", "FUTURE": "futures"}.get(trip["kind"], "stocks")
        row = groups.setdefault(label, {"trips": 0, "pnl": 0.0, "wins": 0})
        row["trips"] += 1
        row["pnl"] = round(row["pnl"] + trip["pnl"], 2)
        row["wins"] += trip["pnl"] > 0
    return groups


@router.post("/sync")
async def sync_journal(
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    return await sync_user_trades(db.db, db.redis, credentials, user.id)


@router.post("/import/zerodha-console")
async def import_console_csv(
    body: ImportRequest,
    user: User = Depends(get_current_user), store: JournalStore = Depends(get_journal_store),
):
    try:
        trades, skipped = parse_console_tradebook(body.csv)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    imported = await store.add_trades(user.id, "kite", trades, source="console_csv")
    return {"imported": imported, "duplicates": len(trades) - imported, "skipped": skipped}


@router.post("/import/upstox-history")
async def import_upstox(
    body: HistoryRequest = HistoryRequest(),
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    from backend.brokers.trades import today_ist
    from datetime import timedelta
    end = today_ist()
    try:
        return await import_upstox_history(db.db, db.redis, credentials, user.id, end - timedelta(days=body.days), end)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # Upstox refused or is down: say so, don't 500
        raise HTTPException(status_code=502, detail=f"Upstox did not return the trade history: {exc}")


@router.put("/round-trips/{round_trip_id}/note")
async def set_round_trip_note(
    round_trip_id: str, body: NoteRequest,
    user: User = Depends(get_current_user), store: JournalStore = Depends(get_journal_store),
):
    # The id embeds the owner (user:broker:trade_id); refuse anyone else's.
    if not round_trip_id.startswith(f"{user.id}:"):
        raise HTTPException(status_code=404, detail="Round trip not found")
    tags = sorted({t.strip().lower() for t in body.tags if t.strip()})
    await store.set_note(user.id, round_trip_id, body.note.strip(), tags)
    return {"note": body.note.strip(), "tags": tags}


@router.get("/beta-metrics")
async def get_beta_metrics(_admin: User = Depends(require_admin)):
    """Phase 12: is anyone coming back? Admin only -- it counts every user."""
    return await beta_metrics(db.db)
