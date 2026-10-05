"""/broker/{broker}/* -- connecting a real broker session, for any broker in
backend.brokers.registry.BROKERS.

Everything here is per-user: the caller's own credentials come from the
encrypted store, and the resulting access token is cached under a key scoped
to them. Connecting binds *that user* to their own broker account, never the
deployment to one shared account (see backend/auth/broker_credentials.py).

Kite and Upstox share a redirect-based connect flow (a login_url the human
visits, then a short-lived code exchanged for a token). Angel One has no
redirect at all -- the human submits client code, password, and a fresh TOTP
directly. `POST .../connect` accepts whatever fields the chosen broker's
`connect()` needs; the caller decides which fields to send based on whether
`login_url` came back non-null.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth.broker_credentials import BrokerCredentialStore, get_credential_store
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.brokers.protocol import BrokerSessionState
from backend.brokers.registry import BROKERS, UnknownBroker, get_broker_adapter
from backend.database import db
from backend.instruments.loader import refresh_instruments_from_adapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/broker", tags=["Broker"])


async def _adapter(broker: str, user: User, credentials: BrokerCredentialStore):
    try:
        return await get_broker_adapter(broker, user.id, credentials, db.redis)
    except UnknownBroker as exc:
        raise HTTPException(status_code=404, detail=str(exc))


_ACTION = {
    BrokerSessionState.UNCONFIGURED: "Add your API credentials in Settings",
    BrokerSessionState.NEEDS_LOGIN: "Connect your account",
    BrokerSessionState.DEGRADED: "Session expired -- reconnect",
    BrokerSessionState.ACTIVE: None,
}


class ConnectRequest(BaseModel):
    request_token: str | None = None  # Kite / Upstox
    client_code: str | None = None  # Angel One
    password: str | None = None  # Angel One
    totp: str | None = None  # Angel One


@router.get("/list")
async def list_brokers():
    return {"brokers": sorted(BROKERS)}


@router.get("/{broker}/status")
async def broker_status(
    broker: str,
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    adapter = await _adapter(broker, user, credentials)
    state = await adapter.state()
    return {
        "state": state.value,
        "connected": state == BrokerSessionState.ACTIVE,
        "action": _ACTION[state],
    }


@router.get("/{broker}/login-url")
async def broker_login_url(
    broker: str,
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    """None means this broker has no redirect step -- the frontend should
    show the credential form directly rather than a "visit this URL" button."""
    adapter = await _adapter(broker, user, credentials)
    try:
        return {"url": await adapter.login_url()}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{broker}/connect")
async def broker_connect(
    broker: str,
    body: ConnectRequest,
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    adapter = await _adapter(broker, user, credentials)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}

    try:
        await adapter.connect(**fields)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"Missing field for {broker}: {exc}")
    except Exception as exc:
        logger.warning("%s connect failed for user %s: %s", broker, user.id, exc)
        raise HTTPException(status_code=502, detail=f"{broker} rejected the connection attempt")

    # Best-effort and truly off the response: expands the shared instrument
    # master (NSE/BSE, then F&O for option contracts) from the broker just
    # connected. It used to be awaited here -- for Kite that is ~60,000
    # instruments, so the connect hit Nginx's 60s timeout (2026-10-05).
    task = asyncio.create_task(_refresh_instruments(adapter, broker))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)

    return {"state": (await adapter.state()).value, "connected": True}


_BACKGROUND: set = set()  # strong refs, so a refresh task is not garbage-collected


async def _refresh_instruments(adapter, broker: str) -> None:
    count = await refresh_instruments_from_adapter(adapter)
    if count:
        logger.info("Instrument master expanded from %s: %d upserted.", broker, count)
    nfo_count = await refresh_instruments_from_adapter(adapter, exchanges=("NFO",))
    if nfo_count:
        logger.info("NFO instrument master expanded from %s: %d upserted.", broker, nfo_count)


@router.post("/{broker}/disconnect")
async def broker_disconnect(
    broker: str,
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    adapter = await _adapter(broker, user, credentials)
    await adapter.disconnect()
    return {"state": (await adapter.state()).value, "connected": False}
