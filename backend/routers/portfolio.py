"""/portfolio -- the user's real long-term holdings across their connected
brokers, how they are doing, and a rule-scored verdict on each.

Verdicts are deployment-gated (AppSettingsStore.portfolio_verdicts): until
it is "all", only admins see SELL / HOLD / ADD; everyone else sees the same
facts and reasons, with a SELL shown as "review first". Showing verdicts to
every user needs SEBI Research Analyst registration (PRODUCT.md).
"""

from fastapi import APIRouter, Depends, HTTPException

from backend.app_settings import AppSettingsStore
from backend.auth.broker_credentials import BrokerCredentialStore, get_credential_store
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.portfolio.service import latest_snapshot, refresh_portfolio

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


def present(snapshot: dict, show_verdicts: bool) -> dict:
    snapshot = {k: v for k, v in snapshot.items() if k not in ("_id", "raw_holdings")}
    snapshot["verdicts_visible"] = show_verdicts
    if show_verdicts:
        return snapshot

    def mask(verdict):
        return "REVIEW" if verdict in ("SELL", "REVIEW") else None

    snapshot["holdings"] = [
        {**row, "verdict": mask(row.get("verdict")), "previous_verdict": mask(row.get("previous_verdict")),
         "score": None}
        for row in snapshot.get("holdings", [])
    ]
    return snapshot


async def verdicts_visible_to(user: User) -> bool:
    return user.role == "admin" or await AppSettingsStore(db.db).get_portfolio_verdicts() == "all"


@router.get("")
async def get_portfolio(user: User = Depends(get_current_user)):
    """The last analysed snapshot, or 404 before the first refresh."""
    snapshot = await latest_snapshot(db.db, user.id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No portfolio analysed yet")
    return present(snapshot, await verdicts_visible_to(user))


@router.post("/refresh")
async def refresh(
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    snapshot = await refresh_portfolio(db.db, user.id, credentials, db.redis)
    if not snapshot["holdings"] and not snapshot["errors"]:
        raise HTTPException(status_code=409, detail="Connect a broker in Settings to read your holdings.")
    return present(snapshot, await verdicts_visible_to(user))
