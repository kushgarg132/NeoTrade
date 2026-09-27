"""/portfolio -- the user's real long-term holdings across their connected
brokers, and how they are doing. Facts only for now: no verdicts."""

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.broker_credentials import BrokerCredentialStore, get_credential_store
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.portfolio.service import latest_snapshot, refresh_portfolio

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


@router.get("")
async def get_portfolio(user: User = Depends(get_current_user)):
    """The last analysed snapshot, or 404 before the first refresh."""
    snapshot = await latest_snapshot(db.db, user.id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No portfolio analysed yet")
    return snapshot


@router.post("/refresh")
async def refresh(
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    snapshot = await refresh_portfolio(db.db, user.id, credentials, db.redis)
    if not snapshot["holdings"] and not snapshot["errors"]:
        raise HTTPException(status_code=409, detail="Connect a broker in Settings to read your holdings.")
    snapshot.pop("_id", None)
    return snapshot
