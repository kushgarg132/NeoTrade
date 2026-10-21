"""/chat/actions/* -- the only way an action the chat proposed gets run:
the user's Confirm (or Cancel) on its card. See backend/chat/actions.py."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth.broker_credentials import get_credential_store
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.chat.actions import ActionRefused, ChatActionStore, confirm
from backend.database import db
from backend.risk.live_confirm import TokenRefused

router = APIRouter(prefix="/chat/actions", tags=["Chat"])


def _db():
    return db.db


class ConfirmRequest(BaseModel):
    confirm_token: Optional[str] = None  # from the first call on a real-money card


@router.get("/pending")
async def pending_actions(user: User = Depends(get_current_user)):
    """Cards waiting for the user's Confirm, for the decisions page."""
    return await ChatActionStore(_db()).pending(user.id)


@router.post("/{action_id}/confirm")
async def confirm_action(
    action_id: str, body: ConfirmRequest = ConfirmRequest(),
    user: User = Depends(get_current_user), credentials=Depends(get_credential_store),
):
    try:
        return await confirm(_db(), db.redis, credentials, user.id, action_id, confirm_token=body.confirm_token)
    except TokenRefused as exc:
        return exc.response()
    except ActionRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{action_id}/cancel")
async def cancel_action(action_id: str, user: User = Depends(get_current_user)):
    if not await ChatActionStore(_db()).cancel(user.id, action_id):
        raise HTTPException(status_code=409, detail="Nothing to cancel.")
    return {"status": "CANCELLED"}
