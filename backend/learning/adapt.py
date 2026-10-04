"""Bounded rules learned from a user's closed paper trades, applied by
size_intents (backend/engine/runner.py) to every later run:

- pause: a strategy losing net of charges over PAUSE_AFTER trades stops
  trading. It resumes only after a newer passing backtest gate result
  (backend/risk/backtest_gate.py), and then is judged afresh from that day.
- floor: when a strategy's weak signals lose and its stronger ones do not,
  its own strength floor rises by at most FLOOR_STEP a night, never past
  FLOOR_CAP. It only ever tightens composite.RULE_FLOOR, never loosens it.
- regime: a strategy that loses with the Nifty on one side of its 200-day
  average stops trading on that side.

Statistics decide here, never the LLM. Every change is logged in
`learning_changes` with what it was before and why, so it can be undone.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from backend.learning.attribution import STRENGTH_BUCKETS, attribute, regime_on
from backend.scoring.composite import RULE_FLOOR

PAUSE_AFTER = 30
FLOOR_STEP = 0.05
FLOOR_CAP = 0.8


@dataclass
class LearnedRules:
    paused: set = field(default_factory=set)
    floors: dict = field(default_factory=dict)
    skip_regimes: dict = field(default_factory=dict)
    regime: Optional[str] = None  # today's

    def blocks(self, strategy: Optional[str], strength: float) -> Optional[str]:
        """Why a signal from `strategy` may not trade, or None."""
        if strategy is None:
            return None
        if strategy in self.paused:
            return "paused"
        if strength < self.floors.get(strategy, RULE_FLOOR):
            return "below learned floor"
        if self.regime in self.skip_regimes.get(strategy, []):
            return f"skips {self.regime} regime"
        return None


def empty_state() -> dict:
    return {"paused": {}, "floors": {}, "skip_regimes": {}, "reset_at": {}}


def _losing(row: dict) -> bool:
    pf = row["profit_factor"]
    return row["shrunk"] < 0 and pf is not None and pf < 1


def _change(strategy, rule, before, after, row) -> dict:
    return {"strategy": strategy, "rule": rule, "before": before, "after": after,
            "evidence": {k: row[k] for k in ("by", "group", "trades", "net", "win_rate", "profit_factor")}}


def decide(state: dict, rows: list[dict]) -> list[dict]:
    """The changes `rows` (attribution.attribute) call for. Pure."""
    changes = []
    for overall in (r for r in rows if r["by"] == "all"):
        name = overall["strategy"]
        if name in state["paused"]:
            continue
        if overall["trades"] >= PAUSE_AFTER and _losing(overall):
            changes.append(_change(name, "pause", False, True, overall))
            continue
        mine = [r for r in rows if r["strategy"] == name]

        skip = state["skip_regimes"].get(name, [])
        for row in mine:
            if row["by"] == "regime" and _losing(row) and row["group"] not in skip:
                changes.append(_change(name, "regime", skip, sorted(skip + [row["group"]]), row))

        # The top edge of the highest losing strength bucket that has only
        # non-losing buckets above it: signals below it are what lose.
        by_bucket = {r["group"]: r for r in mine if r["by"] == "strength"}
        seen = [(edge, by_bucket[label]) for edge, label in STRENGTH_BUCKETS if label in by_bucket]
        floor = state["floors"].get(name, RULE_FLOOR)
        for (edge, row), (_, above) in zip(seen, seen[1:]):
            if _losing(row) and not _losing(above) and above["net"] >= 0 and floor < edge:
                after = round(min(floor + FLOOR_STEP, edge, FLOOR_CAP), 4)
                changes.append(_change(name, "floor", floor, after, row))
                break
    return changes


def _apply(state: dict, change: dict, now: datetime) -> None:
    name, rule = change["strategy"], change["rule"]
    if rule == "pause":
        state["paused"][name] = now
    elif rule == "resume":
        state["paused"].pop(name, None)
        state["reset_at"][name] = now
    elif rule == "floor":
        state["floors"][name] = change["after"]
    elif rule == "regime":
        state["skip_regimes"][name] = change["after"]


def _utc(value: datetime) -> datetime:
    """Mongo hands datetimes back naive; they were stored as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _state(db, user_id: str) -> dict:
    doc = await db["learning_state"].find_one({"user_id": user_id}) or {}
    return {**empty_state(), **{k: doc[k] for k in empty_state() if k in doc}}


async def _closed_trades(db, user_id: str, reset_at: dict) -> list[dict]:
    trades = await db["paper_trades"].find({
        "user_id": user_id, "venue": "paper", "status": "CLOSED", "strategy": {"$ne": None},
    }).to_list(None)
    trades = [t for t in trades if t.get("exit_at") and t.get("entry_at")
              and (t["strategy"] not in reset_at or _utc(t["exit_at"]) > _utc(reset_at[t["strategy"]]))]
    # Trades opened before Order.context existed: an approved suggestion
    # still recorded the signal behind it.
    missing = {t["suggestion_id"] for t in trades if not t.get("context") and t.get("suggestion_id")}
    if missing:
        found = {s["id"]: s for s in await db["suggestions"].find(
            {"user_id": user_id, "id": {"$in": list(missing)}}).to_list(None)}
        for t in trades:
            s = found.get(t.get("suggestion_id")) if not t.get("context") else None
            if s:
                t["context"] = {"strength": s.get("strength"), "reason_codes": s.get("reason_codes") or []}
    return trades


async def learn(db, user_id: str, nifty: list, now: datetime) -> list[dict]:
    """One nightly pass for one user: resume what earned it, judge the rest,
    save and log every change. Returns the changes."""
    state = await _state(db, user_id)
    changes = []
    for name, since in list(state["paused"].items()):
        gate = await db["strategy_backtests"].find_one({"strategy_name": name}, sort=[("run_at", -1)])
        if gate and gate["passed"] and _utc(gate["run_at"]) > _utc(since):
            change = {"strategy": name, "rule": "resume", "before": True, "after": False,
                      "evidence": {"gate_run_at": gate["run_at"]}}
            _apply(state, change, now)
            changes.append(change)

    rows = attribute(await _closed_trades(db, user_id, state["reset_at"]), nifty)
    for change in decide(state, rows):
        _apply(state, change, now)
        changes.append(change)

    # Today's regime, for tomorrow's runs to read without fetching the Nifty.
    state["regime"] = regime_on(nifty[-1][0], nifty) if nifty else None
    await db["learning_state"].update_one({"user_id": user_id}, {"$set": state}, upsert=True)
    if changes:
        await db["learning_changes"].insert_many([{**c, "user_id": user_id, "at": now} for c in changes])
    return changes


async def load_rules(db, user_id: str) -> LearnedRules:
    doc = await db["learning_state"].find_one({"user_id": user_id}) or {}
    return LearnedRules(
        paused=set(doc.get("paused") or {}), floors=doc.get("floors") or {},
        skip_regimes=doc.get("skip_regimes") or {}, regime=doc.get("regime"),
    )
