"""/settings/* -- per-user preferences and broker credentials, plus the
deployment-wide LLM model an admin controls.

This router used to rewrite .env on disk and mutate the in-process `settings`
singleton from a plain signed-in request, which meant any user could overwrite
the broker credentials and model choice for everyone. Both of those endpoints
are gone: credentials are per-user and encrypted (backend/auth/broker_credentials.py),
and the deployment model lives in Mongo behind an admin check.
"""

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

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


class RebalanceTargets(BaseModel):
    rule: Literal["equal", "cap", "conviction"] = "cap"  # conviction: only where verdicts are visible
    max_stock_pct: float = Field(default=15, gt=0, le=100, allow_inf_nan=False)
    max_sector_pct: float = Field(default=30, gt=0, le=100, allow_inf_nan=False)
    overrides: dict[str, float] = Field(default_factory=dict, max_length=100)

    @field_validator("overrides")
    @classmethod
    def _overrides(cls, value):
        if any(not 0 < pct <= 100 for pct in value.values()):
            raise ValueError("each override is a percentage above 0 and at most 100")
        if sum(value.values()) > 100:
            raise ValueError("overrides add up to more than 100%")
        return value


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
    max_option_trades_per_day: Optional[int] = Field(default=None, ge=0, le=500)
    max_option_lots: Optional[int] = Field(default=None, ge=0, le=1000)
    warn_naked_options: Optional[bool] = None
    portfolio_max_loss_pct: Optional[float] = Field(default=None, gt=0, le=100)
    portfolio_max_weight_pct: Optional[float] = Field(default=None, gt=0, le=100)
    auto_square_off: Optional[Literal["off", "preview", "live"]] = None
    auto_paper_intraday: Optional[bool] = None
    auto_paper_longterm: Optional[bool] = None
    broker_roles: Optional[dict[str, str]] = None
    autopilot_enabled: Optional[bool] = None
    autopilot_live: Optional[bool] = None
    autopilot_capital: Optional[float] = Field(default=None, ge=0)
    autopilot_per_trade_cap: Optional[float] = Field(default=None, ge=0)
    autopilot_max_trades_per_day: Optional[int] = Field(default=None, ge=0, le=100)
    autopilot_daily_loss_limit: Optional[float] = Field(default=None, ge=0)
    rebalance_targets: Optional[RebalanceTargets] = None

    @field_validator("broker_roles")
    @classmethod
    def _roles(cls, value):
        from backend.brokers.roles import validate_roles
        return validate_roles(value) if value is not None else value


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
    fields = patch.model_dump(exclude_none=True)
    # No AI account means nothing for the autopilot to trade: switch it off.
    if "broker_roles" in fields and "ai" not in fields["broker_roles"].values():
        fields["autopilot_enabled"] = False
    return await prefs.update(user.id, fields)


@router.get("/settings/autopilot/log")
async def autopilot_log(user: User = Depends(get_current_user)):
    """The autopilot's last 30 orders and refusals, newest first."""
    from backend.database import db

    rows = await db.db["autopilot_log"].find({"user_id": user.id}, {"_id": 0, "user_id": 0}) \
        .sort("at", -1).limit(30).to_list(length=30)
    for row in rows:  # Mongo hands back naive UTC; say so to the browser
        if row.get("at") is not None and row["at"].tzinfo is None:
            row["at"] = row["at"].replace(tzinfo=timezone.utc)
    return {"rows": rows}


@router.get("/settings/strategies")
async def list_strategies(user: User = Depends(get_current_user)):
    """Plain strategy-name list for the Settings page's live/paper toggles --
    universe is a placeholder since strategy construction needs one but the
    name list doesn't depend on it."""
    from backend.strategies.registry import build_default_strategies

    return [s.spec.name for s in build_default_strategies(universe=["PLACEHOLDER"], option_universe=["PLACEHOLDER"])]


@router.get("/settings/strategies/promotion")
async def strategy_promotion(
    user: User = Depends(get_current_user),
    prefs: PrefsStore = Depends(get_prefs_store),
):
    """What each strategy still needs before its live switch sends real
    orders: a passing backtest, and a paper record in this account that
    clears backend/risk/paper_gate.py. Until both hold, a strategy switched
    live keeps trading paper."""
    from backend.risk.backtest_gate import BacktestGateStore
    from backend.risk.paper_gate import paper_records
    from backend.strategies.registry import build_default_strategies

    names = [s.spec.name for s in build_default_strategies(universe=["PLACEHOLDER"], option_universe=["PLACEHOLDER"])]
    account_size = (await prefs.get(user.id))["account_size"]
    records = await paper_records(db.db, user.id, names, account_size)
    gate = BacktestGateStore(db.db)
    rows = []
    for name in names:
        backtest = await gate.latest(name)
        passed = bool(backtest and backtest["passed"])
        summary = None
        if backtest:
            result = backtest["result"]
            summary = {
                "run_at": backtest["run_at"], "trades": result["total_trades"],
                "profit_factor": result["profit_factor"], "max_drawdown": result["max_drawdown"],
                "days": (datetime.fromisoformat(result["end_date"]) - datetime.fromisoformat(result["start_date"])).days,
            }
        rows.append({
            "name": name, "backtest_passed": passed, "backtest": summary, "paper": records[name],
            "eligible": passed and records[name]["passed"],
        })
    return rows


class PortfolioVerdictsRequest(BaseModel):
    audience: Literal["admin", "all"]


@router.get("/settings/portfolio-verdicts")
async def get_portfolio_verdicts(
    app_settings: AppSettingsStore = Depends(get_app_settings_store),
    _admin: User = Depends(require_admin),
):
    return {"audience": await app_settings.get_portfolio_verdicts()}


@router.put("/settings/portfolio-verdicts")
async def set_portfolio_verdicts(
    body: PortfolioVerdictsRequest,
    app_settings: AppSettingsStore = Depends(get_app_settings_store),
    _admin: User = Depends(require_admin),
):
    """Deployment-wide: switching to "all" shows verdicts to every user,
    which needs SEBI Research Analyst registration first."""
    await app_settings.set_portfolio_verdicts(body.audience)
    return {"audience": body.audience}


async def _gateway_models() -> list[dict]:
    """OmniRoute's OpenAI-compatible GET /models, full entries."""
    # The gateway requires its key on /models too, same as on completions.
    headers = {"Authorization": f"Bearer {settings.OMNIROUTE_API_KEYS[0]}"} if settings.OMNIROUTE_API_KEYS else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.OMNIROUTE_BASE_URL}/models", headers=headers)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch OmniRoute model list: {e}")
        raise HTTPException(status_code=502, detail="Could not reach OmniRoute gateway")
    return resp.json().get("data", [])


@router.get("/settings/omniroute-models")
async def list_omniroute_models():
    """Every model id the gateway lists, for the picker's Search all."""
    return [{"id": m["id"]} for m in await _gateway_models()]


@router.get("/settings/omniroute-catalog")
async def omniroute_catalog():
    """The same list as a Family -> Model line -> Version tree, chat models
    only, for the step-by-step picker (backend/model_catalog.py)."""
    from backend.model_catalog import build_catalog

    return build_catalog(await _gateway_models())


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


USAGE_CACHE_SECONDS = 60
_USAGE_CACHE: dict = {}  # {"at": monotonic seconds, "body": dict}


def _family(name: str) -> str:
    lowered = name.lower()
    if lowered.startswith("gemini"):
        return "Gemini"
    if lowered.startswith(("claude", "gpt")):
        return "Claude & GPT"
    return name.replace("_", " ").capitalize()


def _pools(quotas: dict) -> list[dict]:
    """A provider's quotas grouped the way its limits actually work: every
    Gemini model draws on one pool, Claude and GPT on another, and a
    `*_weekly` entry is that family's weekly cap. Counters with no reset
    time (antigravity's `chat_<n>`) are internal and left out."""
    pools: dict[str, dict] = {}
    for name, quota in quotas.items():
        pct = quota.get("remainingPercentage")
        if pct is None or (name.startswith("chat_") and not quota.get("resetAt")):
            continue
        weekly = name.endswith("_weekly")
        label = _family(name) + (" · weekly" if weekly else "")
        pool = pools.setdefault(label, {"label": label, "remaining_pct": pct, "reset_at": quota.get("resetAt"), "models": []})
        pool["remaining_pct"] = min(pool["remaining_pct"], pct)
        if quota.get("resetAt") and (not pool["reset_at"] or quota["resetAt"] < pool["reset_at"]):
            pool["reset_at"] = quota["resetAt"]
        if not weekly:
            pool["models"].append(name)
    for pool in pools.values():
        pool["models"].sort()
    order = {"Gemini": 0, "Claude & GPT": 1}
    return sorted(pools.values(), key=lambda p: (" · weekly" in p["label"], order.get(p["label"].split(" · ")[0], 2), p["label"]))


def _shape_usage(status: dict) -> dict:
    tokens = (status.get("usage") or {}).get("tokens") or {}
    cost = (status.get("usage") or {}).get("cost") or {}
    providers = []
    for account in status.get("accountQuotas") or []:
        quotas = [
            {"name": name, "remaining_pct": quota.get("remainingPercentage"), "reset_at": quota.get("resetAt")}
            for name, quota in (account.get("quotas") or {}).items()
        ]
        providers.append({
            "provider": account.get("provider"), "plan": account.get("plan"),
            "available": account.get("available", True) is not False, "reason": account.get("reason"),
            "quotas": quotas, "pools": _pools(account.get("quotas") or {}),
        })
    return {
        "key_name": (status.get("apiKey") or {}).get("name"),
        "tokens": {
            "input": tokens.get("inputTokens", 0), "output": tokens.get("outputTokens", 0),
            "reasoning": tokens.get("reasoningTokens", 0), "total": tokens.get("totalTokens", 0),
            "since": tokens.get("periodStartAt"),
        },
        "cost": {"used_usd": cost.get("usedUsd"), "limit_usd": cost.get("limitUsd"), "reset_at": cost.get("resetAt")},
        "providers": providers,
    }


class UsageUnavailable(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


async def fetch_usage() -> dict:
    """This deployment's gateway key: its tokens and cost this month, and each
    provider account's remaining quota, from OmniRoute's self-service
    GET /v1/me/status (the key's default `self:usage` scope -- no management
    key needed). Provider quotas are the gateway's shared accounts, not this
    key's share. Cached a minute. Shared by the Settings sheet and Telegram's
    /usage; raises UsageUnavailable."""
    import time

    if _USAGE_CACHE and time.monotonic() - _USAGE_CACHE["at"] < USAGE_CACHE_SECONDS:
        return _USAGE_CACHE["body"]
    if not settings.OMNIROUTE_API_KEYS:
        raise UsageUnavailable(409, "No gateway key configured")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{settings.OMNIROUTE_BASE_URL}/me/status",
                headers={"Authorization": f"Bearer {settings.OMNIROUTE_API_KEYS[0]}"},
            )
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch OmniRoute usage: {e}")
        raise UsageUnavailable(502, "Could not read usage from the OmniRoute gateway")
    body = _shape_usage(resp.json())
    _USAGE_CACHE.update(at=time.monotonic(), body=body)
    return body


@router.get("/settings/omniroute-usage")
async def omniroute_usage(_admin: User = Depends(require_admin)):
    try:
        return await fetch_usage()
    except UsageUnavailable as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)


MODEL_TEST_TIMEOUT_SECONDS = 30


@router.post("/settings/omniroute-model/test")
async def test_omniroute_model(update: ModelUpdate, _admin: User = Depends(require_admin)):
    """One tiny prompt to `model` through the gateway, before anyone saves it.
    Calls the model directly: LLMService.get_completion turns a failure into
    a reply string, which would read as a pass here."""
    import asyncio
    import time

    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from backend.prompts import render

    model = update.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model cannot be empty")
    if not settings.OMNIROUTE_API_KEYS:
        return {"ok": False, "model": model, "latency_ms": None, "reply": None, "error": "No gateway key configured"}

    system, prompt = render("model_test")
    llm = ChatOpenAI(
        model=model, api_key=settings.OMNIROUTE_API_KEYS[0], base_url=settings.OMNIROUTE_BASE_URL,
        temperature=0.0, max_retries=0,
    )
    started = time.monotonic()
    try:
        response = await asyncio.wait_for(
            llm.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)]),
            timeout=MODEL_TEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        error = f"No answer within {MODEL_TEST_TIMEOUT_SECONDS}s"
    except Exception as e:
        error = str(e)[:300]
    else:
        latency = round((time.monotonic() - started) * 1000)
        reply = (response.content or "").strip()[:200] if isinstance(response.content, str) else str(response.content)[:200]
        if not reply:
            return {"ok": False, "model": model, "latency_ms": latency, "reply": None, "error": "Empty reply"}
        return {"ok": True, "model": model, "latency_ms": latency, "reply": reply, "error": None}
    logger.warning(f"Model test failed for {model!r}: {error}")
    return {"ok": False, "model": model, "latency_ms": round((time.monotonic() - started) * 1000), "reply": None, "error": error}


class TierUpdate(BaseModel):
    tier: Literal["fast", "standard", "deep"]
    model: Optional[str] = None


@router.get("/settings/omniroute-tiers")
async def get_omniroute_tiers(app_settings: AppSettingsStore = Depends(get_app_settings_store)):
    """Which model each kind of task runs on. A tier left unset uses
    `fallback`, the single model below it. Fast: event tagging, symbol
    resolution, per-article sentiment. Standard: research reports and
    theses, index explanations. Deep: chat, portfolio review, news scoring
    and peers (see backend/tests/test_llm_call_tiers.py)."""
    return {
        "tiers": await app_settings.get_llm_tiers(),
        "fallback": await app_settings.get_llm_model() or settings.OMNIROUTE_MODEL,
    }


@router.post("/settings/omniroute-tiers")
async def set_omniroute_tier(
    update: TierUpdate,
    _admin: User = Depends(require_admin),
    app_settings: AppSettingsStore = Depends(get_app_settings_store),
):
    model = (update.model or "").strip() or None
    await app_settings.set_llm_tier(update.tier, model)
    logger.info(f"OmniRoute {update.tier} tier set to {model!r}.")
    return {"tier": update.tier, "model": model}


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
