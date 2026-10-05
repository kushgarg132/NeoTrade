"""What a strategy is for, in words the planner, chat and UI can read.
Static and I/O-free; the live record is joined on in backend/learning/library.py."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Regime = Literal["risk_on", "neutral", "risk_off"]
Need = Literal["gap", "volume_spike", "range_day", "trend_day", "catalyst", "sector_move"]


class StrategyCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    style: Literal["breakout", "reversion", "momentum", "options", "value"]
    regimes: list[Regime] = Field(min_length=1)
    needs: list[Need]
    best_when: str
    avoid_when: str
    typical_hold_minutes: int
