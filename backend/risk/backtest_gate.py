"""The backtest gate: a strategy may run live only if its most recently
stored BacktestResult clears docs/ROADMAP.md Phase 3's thresholds. The
mechanism, not any specific strategy's fate -- a strategy that fails stays
out of live trading until a re-tested, improved version passes; that's the
gate doing its job, not a bug to work around.
"""

from datetime import datetime, timezone

from backend.components.shared.models import BacktestResult

MIN_WINDOW_DAYS = 365
# What a gate backtest asks for: the actual span runs from the first bar to the
# last, so a request of exactly 365 days always comes back a day or two short.
LOOKBACK_DAYS = 372
MIN_TRADES = 30
MIN_PROFIT_FACTOR = 1.3
MAX_DRAWDOWN = 0.15


def passes_gate(result: BacktestResult) -> bool:
    window_days = (result.end_date - result.start_date).days
    return (
        window_days >= MIN_WINDOW_DAYS
        and result.total_trades >= MIN_TRADES
        and result.profit_factor >= MIN_PROFIT_FACTOR
        and result.max_drawdown <= MAX_DRAWDOWN
    )


class BacktestGateStore:
    """Collection `strategy_backtests`: one document per (strategy_name,
    run), never overwritten -- history is kept so a strategy's track record
    over time stays visible, but `live_eligible` always follows the most
    recent run only."""

    def __init__(self, db) -> None:
        self._db = db

    @property
    def collection(self):
        return self._db["strategy_backtests"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("strategy_name", 1), ("run_at", -1)])

    async def record(self, strategy_name: str, result: BacktestResult) -> None:
        await self.collection.insert_one({
            "strategy_name": strategy_name,
            "run_at": datetime.now(timezone.utc),
            "passed": passes_gate(result),
            "result": result.model_dump(mode="json"),
        })

    async def latest(self, strategy_name: str) -> dict | None:
        cursor = (
            self.collection.find({"strategy_name": strategy_name})
            .sort([("run_at", -1), ("_id", -1)])
            .limit(1)
        )
        docs = await cursor.to_list(length=1)
        return docs[0] if docs else None

    async def live_eligible(self, strategy_name: str) -> bool:
        doc = await self.latest(strategy_name)
        return bool(doc and doc["passed"])
