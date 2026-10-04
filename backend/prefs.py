"""Per-user trading preferences (collection `user_prefs`).

What the scheduler scans, and the account size and exposure cap it sizes
against, are the user's own settings -- the engine used to take them from
whatever the /trading/start request happened to send, which leaves a
scheduled scan with nothing to go on.
"""

from datetime import datetime, timezone
from typing import Optional

from backend.components.quant.indian_stocks import ALL_SCAN_STOCKS

DEFAULTS = {
    "universe": list(ALL_SCAN_STOCKS),
    "account_size": 1_000_000.0,
    "max_exposure": 1_000_000.0,  # per-day capital cap: total exposure allowed at once
    "per_trade_cap": 100_000.0,  # hard notional ceiling for any single trade
    "daily_loss_limit": 50_000.0,  # kill-switch trigger: cumulative loss for the day
    "scan_enabled": True,
    "omniroute_model": None,
    "live_strategies": [],  # strategy names the user has toggled to trade with real orders
    # Guardrails (backend/guardrails/): watch the user's own broker activity
    # during the session. Off until the user turns it on; 0 turns a rule off.
    "guardrails_enabled": False,
    "max_trades_per_day": 0,
    "cooldown_after_losses": 0,
    "cooldown_minutes": 30,
    # Options guardrails (0/False is off): options round trips opened per
    # day, lots in any one options trade, and a warning on selling an option
    # with no bought option on the same underlying to cap the loss.
    "max_option_trades_per_day": 0,
    "max_option_lots": 0,
    "warn_naked_options": False,
    # What happens to open NSE intraday positions when the daily loss limit
    # is hit: "off", "preview" (alert with the orders it would place), or
    # "live" (place them). Never defaults to live.
    "auto_square_off": "off",
    # The factor portfolio's own paper allocation (backend/factor/paper.py),
    # apart from account_size: it needs ~₹3 lakh to hold its names in whole shares.
    "factor_paper_capital": 300_000.0,
    # Which connected broker is for what (backend/brokers/roles.py):
    # {"kite": "ai", "upstox": "mine"}. Orders route by role, never by fallback.
    "broker_roles": {},
    # The fenced autopilot on the "ai" account (backend/autopilot/).
    "autopilot_enabled": False,
    "autopilot_live": False,
    "autopilot_capital": 25_000.0,
    "autopilot_per_trade_cap": 5_000.0,
    "autopilot_max_trades_per_day": 5,
    "autopilot_daily_loss_limit": 1_000.0,
    # Start an intraday / long-term paper run by itself every trading day at
    # the open (backend/engine/autorun.py). Paper only; off until turned on.
    "auto_paper_intraday": False,
    "auto_paper_longterm": False,
    # Portfolio review (backend/portfolio/rules.py): a holding this far below
    # its average cost, or this large a share of the portfolio, counts
    # against it.
    "portfolio_max_loss_pct": 25.0,
    "portfolio_max_weight_pct": 20.0,
}

EDITABLE = tuple(DEFAULTS)


class PrefsStore:
    def __init__(self, db) -> None:
        self.collection = db["user_prefs"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("user_id", unique=True)

    async def get(self, user_id: str) -> dict:
        doc = await self.collection.find_one({"user_id": user_id}) or {}
        return {**DEFAULTS, "user_id": user_id, **{k: doc[k] for k in EDITABLE if k in doc}}

    async def update(self, user_id: str, patch: dict) -> dict:
        changes = {k: v for k, v in patch.items() if k in EDITABLE and v is not None}
        if changes:
            changes["updated_at"] = datetime.now(timezone.utc)
            await self.collection.update_one(
                {"user_id": user_id}, {"$set": changes}, upsert=True
            )
        return await self.get(user_id)

    async def scan_enabled_users(self) -> list[dict]:
        """Users the scheduled scan should run for. A user who has never
        opened settings has no document at all, so absence means enabled --
        matching DEFAULTS rather than silently excluding them."""
        cursor = self.collection.find({"scan_enabled": False})
        opted_out = {doc["user_id"] for doc in await cursor.to_list(length=None)}

        users = await self.collection.database["users"].find({}).to_list(length=None)
        return [await self.get(u["id"]) for u in users if u["id"] not in opted_out]
