"""The game plan inside the engine: which (strategy, symbol) pairs may
open risk, how many positions, at what fraction of normal risk. Read by
size_intents next to LearnedRules; it only ever removes or shrinks an
opening order, and with no plan it does nothing."""

from datetime import datetime
from typing import Awaitable, Callable, Optional

from backend.engine.session import IST

PlanSource = Callable[[datetime], Awaitable[Optional[dict]]]


class PlanGate:
    def __init__(self, source: PlanSource) -> None:
        self._source = source
        self._at: Optional[datetime] = None
        self._plan: Optional[dict] = None
        self._allowed: set[tuple[str, str]] = set()

    async def refresh(self, now: datetime) -> None:
        """At most one read per bar time: live, a Redis GET per bar."""
        if now == self._at:
            return
        self._at, self._plan = now, await self._source(now)
        self._allowed = {(name, a["symbol"]) for a in (self._plan or {}).get("allow") or []
                         for name in a.get("strategies") or []}

    @property
    def multiplier(self) -> float:
        return float(self._plan.get("risk_multiplier", 1.0)) if self._plan else 1.0

    def blocks(self, strategy: Optional[str], symbol: str, holding: bool, open_positions: int) -> Optional[str]:
        """Why an opening intent may not trade under today's plan, or None."""
        if not self._plan:
            return None
        if self._plan.get("skip_day"):
            return "plan: skip day"
        if (strategy, symbol) not in self._allowed:
            return "plan: not in today's plan"
        if not holding and open_positions >= self._plan.get("max_positions", 0):
            return "plan: max positions"
        return None


def redis_source(redis, user_id: str) -> PlanSource:
    from backend.plan import store

    async def source(now: datetime) -> Optional[dict]:
        return await store.current(redis, user_id, now.astimezone(IST).date())
    return source


def versions_source(versions: list[dict]) -> PlanSource:
    """The version in force at each moment of a past day (the replay)."""
    async def source(now: datetime) -> Optional[dict]:
        live = [v for v in versions if v["at"] <= now]
        return live[-1] if live else None
    return source
