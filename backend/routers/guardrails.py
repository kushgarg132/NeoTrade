"""/guardrails/* -- today's guardrail breaches, and linking Telegram for
alerts. The rules themselves are ordinary preferences (/settings/preferences)."""

import secrets
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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
    bot = await store.telegram_bot(user.id)
    return {
        "events": await store.events_for(user.id, day),
        "telegram": {
            # Can this user link at all: their own bot, or the server's.
            "configured": bool(bot) or telegram.configured(),
            "linked": bool(await store.telegram_chat(user.id)),
            # Their own bot's @username; never the token.
            "own_bot": bot["username"] if bot else None,
        },
    }


class BotRequest(BaseModel):
    token: str = Field(min_length=20, max_length=100, pattern=r"^\d+:[A-Za-z0-9_-]+$")


@router.put("/telegram/bot")
async def telegram_set_bot(
    req: BotRequest,
    user: User = Depends(get_current_user), store: GuardrailStore = Depends(get_guardrail_store),
):
    """Use the user's own bot (made with @BotFather) for their alerts.
    The token is checked with Telegram before it is stored, encrypted."""
    try:
        username = await telegram.bot_username(req.token)
    except httpx.HTTPError:
        raise HTTPException(status_code=400, detail="Telegram did not accept that token. Copy it again from @BotFather.")
    await store.set_telegram_bot(user.id, req.token, username)
    return {"own_bot": username, "linked": False}


@router.delete("/telegram/bot")
async def telegram_remove_bot(
    user: User = Depends(get_current_user), store: GuardrailStore = Depends(get_guardrail_store),
):
    await store.set_telegram_bot(user.id, None)
    return {"own_bot": None, "linked": False}


async def _bot_token(store: GuardrailStore, user_id: str):
    """The user's own bot token, or None for the server's; 503 when neither exists."""
    bot = await store.telegram_bot(user_id)
    if bot is None and not telegram.configured():
        raise HTTPException(status_code=503, detail="Add your own Telegram bot first: there is no shared bot on this server.")
    return bot["token"] if bot else None


@router.post("/telegram/link")
async def telegram_link(
    user: User = Depends(get_current_user), store: GuardrailStore = Depends(get_guardrail_store),
):
    token = await _bot_token(store, user.id)
    code = secrets.token_urlsafe(12)
    await db.redis.set(_link_key(user.id), code, ex=LINK_TTL_SECONDS)
    return {"url": f"https://t.me/{await telegram.bot_username(token)}?start={code}"}


@router.post("/telegram/verify")
async def telegram_verify(
    user: User = Depends(get_current_user), store: GuardrailStore = Depends(get_guardrail_store),
):
    token = await _bot_token(store, user.id)
    code = await db.redis.get(_link_key(user.id))
    if not code:
        raise HTTPException(status_code=410, detail="The link expired. Start again.")
    chat_id = await telegram.find_chat(code, token)
    if chat_id is None:
        raise HTTPException(status_code=404, detail="No Start message from you yet. Tap Start in Telegram, then check again.")
    await store.set_telegram_chat(user.id, chat_id)
    await db.redis.delete(_link_key(user.id))
    await telegram.send(chat_id, "NeoTrade alerts are on for this chat.", token)
    return {"linked": True}


@router.delete("/telegram")
async def telegram_unlink(
    user: User = Depends(get_current_user), store: GuardrailStore = Depends(get_guardrail_store),
):
    await store.set_telegram_chat(user.id, None)
    return {"linked": False}
