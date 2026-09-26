"""/settings/* -- per-user preferences and broker credentials, plus the
deployment-wide LLM model an admin controls.

This router used to rewrite .env on disk and mutate the in-process `settings`
singleton from a plain signed-in request, which meant any user could overwrite
the broker credentials and model choice for everyone. Both of those endpoints
are gone: credentials are per-user and encrypted (backend/auth/broker_credentials.py),
and the deployment model lives in Mongo behind an admin check.
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app_settings import AppSettingsStore
from backend.auth.broker_credentials import (
    BrokerCredentialStore,
    CredentialEncryptionUnavailable,
    get_credential_store,
)
from backend.auth.dependency import get_current_user, require_admin
from backend.auth.models import User
from backend.configs.settings import settings
from backend.database import db
from backend.prefs import PrefsStore

router = APIRouter()
logger = logging.getLogger(__name__)


def get_prefs_store() -> PrefsStore:
    return PrefsStore(db.db)


def get_app_settings_store() -> AppSettingsStore:
    return AppSettingsStore(db.db)


class PreferencesPatch(BaseModel):
    """Every field optional: the settings page saves one card at a time."""
    universe: Optional[list[str]] = None
    account_size: Optional[float] = None
    max_exposure: Optional[float] = None
    per_trade_cap: Optional[float] = None
    daily_loss_limit: Optional[float] = None
    scan_enabled: Optional[bool] = None
    omniroute_model: Optional[str] = None
    live_strategies: Optional[list[str]] = None
    guardrails_enabled: Optional[bool] = None
    max_trades_per_day: Optional[int] = Field(default=None, ge=0, le=500)
    cooldown_after_losses: Optional[int] = Field(default=None, ge=0, le=20)
    cooldown_minutes: Optional[int] = Field(default=None, ge=0, le=390)


@router.get("/settings/preferences")
async def get_preferences(
    user: User = Depends(get_current_user),
    prefs: PrefsStore = Depends(get_prefs_store),
):
    return await prefs.get(user.id)


@router.put("/settings/preferences")
async def update_preferences(
    patch: PreferencesPatch,
    user: User = Depends(get_current_user),
    prefs: PrefsStore = Depends(get_prefs_store),
):
    return await prefs.update(user.id, patch.model_dump(exclude_none=True))


@router.get("/settings/strategies")
async def list_strategies(user: User = Depends(get_current_user)):
    """Plain strategy-name list for the Settings page's live/paper toggles --
    universe is a placeholder since strategy construction needs one but the
    name list doesn't depend on it."""
    from backend.strategies.registry import build_default_strategies

    return [s.spec.name for s in build_default_strategies(universe=["PLACEHOLDER"])]


@router.get("/settings/omniroute-models")
async def list_omniroute_models():
    """Proxies OmniRoute's OpenAI-compatible GET /models so the frontend can
    offer a searchable picker instead of a hardcoded model string. Returns
    only `id` per entry -- the picker doesn't need context_length/capabilities."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.OMNIROUTE_BASE_URL}/models")
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch OmniRoute model list: {e}")
        raise HTTPException(status_code=502, detail="Could not reach OmniRoute gateway")

    data = resp.json().get("data", [])
    return [{"id": m["id"]} for m in data]


@router.get("/settings/omniroute-model")
async def get_omniroute_model(
    app_settings: AppSettingsStore = Depends(get_app_settings_store),
):
    return {"model": await app_settings.get_llm_model() or settings.OMNIROUTE_MODEL}


class ModelUpdate(BaseModel):
    model: str


@router.post("/settings/omniroute-model")
async def set_omniroute_model(
    update: ModelUpdate,
    _admin: User = Depends(require_admin),
    app_settings: AppSettingsStore = Depends(get_app_settings_store),
):
    """Deployment-wide: every user's requests go through the chosen model, so
    only an admin may change it."""
    new_model = update.model.strip()
    if not new_model:
        raise HTTPException(status_code=400, detail="Model cannot be empty")

    await app_settings.set_llm_model(new_model)
    logger.info(f"OmniRoute model updated to {new_model!r}.")
    return {"message": "Model updated successfully"}


# Angel One's REST flow needs no long-lived secret: the account password and
# TOTP are supplied fresh at connect time (backend/brokers/angel_one.py),
# never stored. Every other broker needs a real secret.
_NO_SECRET_REQUIRED = {"angel_one"}


class BrokerCredentialsUpdate(BaseModel):
    broker: str = "kite"
    api_key: str
    api_secret: Optional[str] = None
    extra: Optional[str] = None  # e.g. Upstox's registered redirect_uri


@router.get("/settings/broker-credentials")
async def get_broker_credentials(
    broker: str = "kite",
    user: User = Depends(get_current_user),
    store: BrokerCredentialStore = Depends(get_credential_store),
):
    """Never returns the secret -- only whether one is stored, and enough of
    the key to recognise which account it is."""
    return await store.status(user.id, broker)


@router.post("/settings/broker-credentials")
async def set_broker_credentials(
    update: BrokerCredentialsUpdate,
    user: User = Depends(get_current_user),
    store: BrokerCredentialStore = Depends(get_credential_store),
):
    api_key = update.api_key.strip()
    api_secret = (update.api_secret or "").strip()
    secret_required = update.broker not in _NO_SECRET_REQUIRED

    if not api_key or (secret_required and not api_secret):
        raise HTTPException(
            status_code=400,
            detail="API key is required" if not secret_required else "Both API key and secret are required",
        )

    try:
        await store.save(
            user.id, update.broker, api_key=api_key,
            api_secret=api_secret or "unused", extra=update.extra,
        )
    except CredentialEncryptionUnavailable:
        logger.error("Refused to store broker credentials: CREDENTIAL_ENCRYPTION_KEY unset")
        raise HTTPException(
            status_code=503,
            detail="Server is missing its credential encryption key; credentials were not saved",
        )

    return await store.status(user.id, update.broker)


@router.delete("/settings/broker-credentials")
async def delete_broker_credentials(
    broker: str = "kite",
    user: User = Depends(get_current_user),
    store: BrokerCredentialStore = Depends(get_credential_store),
):
    await store.delete(user.id, broker)
    return await store.status(user.id, broker)
