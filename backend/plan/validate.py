"""The game plan as code trusts it: whatever the model returns is parsed,
filtered to known strategies and symbols, and clamped so it can only
tighten (docs/superpowers/specs/2026-10-05-ai-game-plan-and-strategy-library-design.md).
Pure; no I/O."""

import json
from typing import Optional

from pydantic import BaseModel

from backend.components.analyst.agent import _extract_json

MAX_PLAN_POSITIONS = 10  # no per-user positions pref exists; the plan's own ceiling
MAX_ADDS = 10
MIN_MULTIPLIER, MAX_MULTIPLIER = 0.25, 1.0
MAX_RATIONALE_LINES, MAX_RATIONALE_CHARS = 5, 200
NO_EXITS = {"pre_open", "fallback"}


class TradePlan(BaseModel):
    trigger: str
    skip_day: bool = False
    risk_multiplier: float = 1.0
    max_positions: int = MAX_PLAN_POSITIONS
    add_symbols: list[str] = []
    allow: list[dict] = []
    exits: list[dict] = []
    rationale: list[str] = []


def _number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _catalyst(value) -> Optional[dict]:
    if not isinstance(value, dict) or "direction" not in value:
        return None
    return {"item_id": str(value.get("item_id") or ""), "direction": max(-1.0, min(1.0, _number(value["direction"], 0.0)))}


def validate(raw: str | dict, *, trigger: str, strategies: set[str], universe: set[str],
             nifty200: set[str]) -> TradePlan:
    data = raw if isinstance(raw, dict) else json.loads(_extract_json(raw))
    if not isinstance(data, dict):
        raise ValueError("plan is not a JSON object")

    adds: list[str] = []
    for s in data.get("add_symbols") or []:
        s = str(s).strip().upper()
        if s in nifty200 and s not in universe and s not in adds:
            adds.append(s)
    adds = adds[:MAX_ADDS]
    allowed_symbols = universe | set(adds)

    allow: dict[str, dict] = {}
    for entry in data.get("allow") or []:
        if not isinstance(entry, dict):
            continue
        symbol = str(entry.get("symbol") or "").strip().upper()
        names = [n for n in entry.get("strategies") or [] if n in strategies]
        if symbol not in allowed_symbols or not names:
            continue
        kept = allow.setdefault(symbol, {"symbol": symbol, "strategies": [], "catalyst": None})
        kept["strategies"] += [n for n in names if n not in kept["strategies"]]
        kept["catalyst"] = kept["catalyst"] or _catalyst(entry.get("catalyst"))

    exits = [] if trigger in NO_EXITS else [
        {"symbol": str(e.get("symbol", "")).upper(), "reason": str(e.get("reason", ""))[:MAX_RATIONALE_CHARS]}
        for e in data.get("exits") or [] if isinstance(e, dict) and str(e.get("symbol", "")).upper() in allowed_symbols]

    return TradePlan(
        trigger=trigger,
        skip_day=bool(data.get("skip_day", False)),
        risk_multiplier=max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, _number(data.get("risk_multiplier"), 1.0))),
        max_positions=max(0, min(MAX_PLAN_POSITIONS, int(_number(data.get("max_positions"), MAX_PLAN_POSITIONS)))),
        add_symbols=adds,
        allow=list(allow.values()),
        exits=exits,
        rationale=[str(line)[:MAX_RATIONALE_CHARS] for line in data.get("rationale") or []][:MAX_RATIONALE_LINES],
    )


def fallback_plan(strategies: set[str], universe: set[str], reason: str) -> TradePlan:
    """Today's behaviour, written down: every strategy on every symbol."""
    names = sorted(strategies)
    return TradePlan(trigger="fallback", allow=[{"symbol": s, "strategies": names, "catalyst": None}
                                                for s in sorted(universe)], rationale=[reason])
