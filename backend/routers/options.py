"""/options/* -- live option chains for the Indian indices, from the user's
own Upstox session. Upstox is the one connected broker with a native chain
endpoint (Kite has none: a chain there means quoting every contract), so a
chain needs an ACTIVE Upstox login and says so plainly when there isn't one.
Read-only market data: nothing here places an order.
"""

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend.auth.broker_credentials import get_credential_store
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.brokers.protocol import BrokerSessionState
from backend.brokers.registry import get_broker_adapter
from backend.database import db

router = APIRouter(prefix="/options", tags=["Options"])

UNDERLYINGS = {
    "NIFTY": {"name": "NIFTY 50", "key": "NSE_INDEX|Nifty 50", "index": "^NSEI"},
    "BANKNIFTY": {"name": "BANK NIFTY", "key": "NSE_INDEX|Nifty Bank", "index": "^NSEBANK"},
}
Underlying = Literal["NIFTY", "BANKNIFTY"]


async def upstox_for(user: User = Depends(get_current_user)):
    adapter = await get_broker_adapter("upstox", user.id, get_credential_store(), db.redis)
    if await adapter.state() != BrokerSessionState.ACTIVE:
        raise HTTPException(
            status_code=409,
            detail="Option chains come from your Upstox session. Connect Upstox in Settings (it logs out daily at 3:30 AM).",
        )
    return adapter


def _upstream(e: httpx.HTTPError):
    return HTTPException(status_code=502, detail=f"Upstox did not return the option data: {e}")


@router.get("/expiries")
async def get_expiries(underlying: Underlying, adapter=Depends(upstox_for)):
    try:
        return await adapter.option_expiries(UNDERLYINGS[underlying]["key"])
    except httpx.HTTPError as e:
        raise _upstream(e)


@router.get("/chain")
async def get_chain(underlying: Underlying, expiry: str, adapter=Depends(upstox_for)):
    try:
        rows = await adapter.option_chain(UNDERLYINGS[underlying]["key"], expiry)
    except httpx.HTTPError as e:
        raise _upstream(e)
    spot = next((row["spot"] for row in rows if row.get("spot")), None)
    atm = min(rows, key=lambda row: abs(row["strike"] - spot))["strike"] if rows and spot else None
    call_oi = sum((row["call"] or {}).get("oi") or 0 for row in rows)
    put_oi = sum((row["put"] or {}).get("oi") or 0 for row in rows)
    return {
        "underlying": underlying,
        "name": UNDERLYINGS[underlying]["name"],
        "expiry": expiry,
        "spot": spot,
        "atm_strike": atm,
        "pcr": put_oi / call_oi if call_oi else None,
        "strikes": rows,
    }
