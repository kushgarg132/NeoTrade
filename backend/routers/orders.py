"""/orders/* -- the order ticket. Proposing stores the same `order` card the
chat makes (backend/chat/actions.py) after the same checks; it runs only on
the user's Confirm at /chat/actions/{id}/confirm, second tap for real money.
There is no way to name the AI account here. Also lists and cancels open
paper limit orders (backend/engine/paper_orders.py)."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.chat.actions import ActionRefused, ChatActionStore, _order_checks
from backend.database import db
from backend.engine import paper_orders

router = APIRouter(prefix="/orders", tags=["Orders"])


def _db():
    return db.db


class TicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    product: Literal["CNC", "MIS"]
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    limit_price: Optional[float] = None
    venue: Literal["paper", "live"]

    @model_validator(mode="after")
    def _limit_needs_price(self):
        if (self.order_type == "LIMIT") != (self.limit_price is not None):
            raise ValueError("limit_price is required for a LIMIT order and only for one")
        return self


@router.post("/propose")
async def propose(body: TicketRequest, user: User = Depends(get_current_user)):
    params = body.model_dump()
    if body.limit_price is not None:
        params["limit_price"] = round(round(body.limit_price / 0.05) * 0.05, 2)  # NSE equity tick
    params["symbol"] = body.symbol.strip().upper().removesuffix(".NS")
    try:
        price, _ = await _order_checks(_db(), user.id, params, None)
    except ActionRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    basis = params["limit_price"] or price
    how = f"limit ₹{params['limit_price']:,.2f}" if body.order_type == "LIMIT" else "market"
    summary = (
        f"{body.side} {body.quantity} {params['symbol']} · {'delivery' if body.product == 'CNC' else 'intraday'}"
        f" · {how} · ~₹{basis * body.quantity:,.0f} on {'paper' if body.venue == 'paper' else 'your account'}"
    )
    return await ChatActionStore(_db()).propose(
        user.id, "order", params, summary, body.venue, body.venue == "live", "order ticket",
    )


@router.get("/paper")
async def open_paper_orders(user: User = Depends(get_current_user)):
    return await paper_orders.list_open(_db(), user.id)


@router.post("/paper/{order_id}/cancel")
async def cancel_paper_order(order_id: str, user: User = Depends(get_current_user)):
    if not await paper_orders.cancel(_db(), user.id, order_id):
        raise HTTPException(status_code=404, detail="No open paper order to cancel.")
    return {"status": "CANCELLED"}
