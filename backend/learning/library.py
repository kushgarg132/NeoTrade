"""The strategy library: each strategy's static card (backend/strategies/card.py)
joined with what is known about it for one user -- the backtest gate, this
user's paper record, the rules learned from it (learning/adapt.py) and its
results by Nifty trend and by reason (learning/attribution.py).

Read by GET /strategies/library, the chat assistant's get_strategy_library
tool and, in Phase 15.2, the game-plan builder. Read-only.
"""

from typing import Literal, Optional

from backend.builder import store
from backend.learning.adapt import _closed_trades, _state, load_rules
from backend.learning.attribution import attribute
from backend.prefs import PrefsStore
from backend.risk.backtest_gate import BacktestGateStore
from backend.risk.paper_gate import paper_records
from backend.strategies.registry import build_default_strategies

STAT_KEYS = ("trades", "net", "win_rate", "profit_factor", "shrunk")


def _strategies(user_id: Optional[str] = None):
    # Same set the Settings page lists: a placeholder universe builds every one.
    return build_default_strategies(universe=["PLACEHOLDER"], option_universe=["PLACEHOLDER"], user_id=user_id)


def strategy_names(user_id: Optional[str] = None) -> list[str]:
    return [s.spec.name for s in _strategies(user_id)]


def _stats(row: Optional[dict]) -> Optional[dict]:
    return {k: row[k] for k in STAT_KEYS} if row else None


async def catalog(db, user_id: str, nifty: list,
                  mode: Optional[Literal["INTRADAY", "LONGTERM"]] = None) -> list[dict]:
    await store.refresh(db)
    strategies = [s for s in _strategies(user_id) if mode is None or s.spec.mode == mode]
    names = [s.spec.name for s in strategies]
    prefs = await PrefsStore(db).get(user_id)
    records = await paper_records(db, user_id, names, prefs["account_size"])
    rules = await load_rules(db, user_id)
    rows = attribute(await _closed_trades(db, user_id, (await _state(db, user_id))["reset_at"]), nifty)
    gate = BacktestGateStore(db)
    live = set(prefs.get("live_strategies") or [])

    built_docs = {f"built:{d['slug']}": d for d in await store.visible(db, user_id)}
    cards = []
    for s in strategies:
        name = s.spec.name
        mine = [r for r in rows if r["strategy"] == name]
        backtest = await gate.latest(name)
        result = (backtest or {}).get("result") or {}
        card = {
            "name": name, "mode": s.spec.mode, "timeframe": s.spec.timeframe,
            "card": s.CARD.model_dump(),
            "backtest": None if backtest is None else {
                "passed": bool(backtest.get("passed")), "profit_factor": result.get("profit_factor"),
                "max_drawdown": result.get("max_drawdown"), "trades": result.get("total_trades"),
                "run_at": backtest.get("run_at"),
            },
            "paper": {"passed": records[name]["passed"], "checks": records[name]["checks"]},
            "learned": {"paused": name in rules.paused, "floor": rules.floors.get(name),
                        "skip_regimes": list(rules.skip_regimes.get(name) or [])},
            "stats": {
                "all": _stats(next((r for r in mine if r["by"] == "all"), None)),
                "by_trend": {g: _stats(next((r for r in mine if r["by"] == "regime" and r["group"] == g), None))
                             for g in ("up", "down")},
                "by_reason": {r["group"]: _stats(r) for r in mine if r["by"] == "reason"},
            },
            "live_switch": name in live,
        }
        if doc := built_docs.get(name):  # the builder's own verdict; never infer pass/fail from the gate alone
            card["built"] = {k: doc.get(k) for k in ("description", "thesis", "metrics", "verdict")}
            card["built"]["horizon"] = (doc.get("spec") or {}).get("horizon", "intraday")
        cards.append(card)
    return sorted(cards, key=lambda c: c["name"])
