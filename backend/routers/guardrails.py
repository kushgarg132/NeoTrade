"""/guardrails/* -- today's guardrail breaches, and linking Telegram for
alerts. The rules themselves are ordinary preferences (/settings/preferences)."""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.engine.session import IST
from backend.guardrails import telegram
from backend.guardrails.store import GuardrailStore

router = APIRouter(prefix="/guardrails", tags=["Guardrails"])

LINK_TTL_SECONDS = 15 * 60


def get_guardrail_store() -> GuardrailStore:
    return GuardrailStore(db.db)


def _link_key(user_id: str) -> str:
    return f"telegram:link:{user_id}"


@router.get("")
async def guardrail_status(
    user: User = Depends(get_current_user), store: GuardrailStore = Depends(get_guardrail_store),
):
    day = datetime.now(timezone.utc).astimezone(IST).date()
    return {
        "events": await store.events_for(user.id, day),
        "telegram": {"configured": telegram.configured(), "linked": bool(await store.telegram_chat(user.id))},
    }


@router.post("/telegram/link")
async def telegram_link(user: User = Depends(get_current_user)):
    if not telegram.configured():
        raise HTTPException(status_code=503, detail="Telegram alerts are not set up on this server")
    code = secrets.token_urlsafe(12)
    await db.redis.set(_link_key(user.id), code, ex=LINK_TTL_SECONDS)
    return {"url": f"https://t.me/{await telegram.bot_username()}?start={code}"}


@router.post("/telegram/verify")
async def telegram_verify(
    user: User = Depends(get_current_user), store: GuardrailStore = Depends(get_guardrail_store),
):
    code = await db.redis.get(_link_key(user.id))
    if not code:
        raise HTTPException(status_code=410, detail="The link expired. Start again.")
    chat_id = await telegram.find_chat(code)
    if chat_id is None:
        raise HTTPException(status_code=404, detail="No Start message from you yet. Tap Start in Telegram, then check again.")
    await store.set_telegram_chat(user.id, chat_id)
    await db.redis.delete(_link_key(user.id))
    await telegram.send(chat_id, "NeoTrade alerts are on for this chat.")
    return {"linked": True}


@router.delete("/telegram")
async def telegram_unlink(
    user: User = Depends(get_current_user), store: GuardrailStore = Depends(get_guardrail_store),
):
    await store.set_telegram_chat(user.id, None)
    return {"linked": False}
