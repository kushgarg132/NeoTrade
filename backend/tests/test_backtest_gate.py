"""The backtest gate: a strategy is live-eligible only if its most recently
stored BacktestResult meets the criteria in docs/ROADMAP.md Phase 3 --
window >=1 year, >=30 trades, profit factor >=1.3, max drawdown <=15%.
"""

from datetime import datetime, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.core.models import BacktestResult
from backend.risk.backtest_gate import BacktestGateStore, passes_gate


def _result(**overrides) -> BacktestResult:
    fields = dict(
        symbol="RELIANCE", start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 1, 2, tzinfo=timezone.utc),  # just over 1 year
        total_trades=40, win_rate=0.55, profit_factor=1.5, total_pnl=50_000.0,
        max_drawdown=0.10, sharpe_ratio=1.2, trades=[],
    )
    fields.update(overrides)
    return BacktestResult(**fields)


def _store():
    return BacktestGateStore(AsyncMongoMockClient()["test_db"])


# --- passes_gate: pure decision -------------------------------------------

def test_a_result_meeting_every_threshold_passes():
    assert passes_gate(_result()) is True


def test_too_short_a_window_fails():
    assert passes_gate(_result(start_date=datetime(2026, 1, 1, tzinfo=timezone.utc))) is False


def test_too_few_trades_fails():
    assert passes_gate(_result(total_trades=29)) is False


def test_exactly_the_trade_threshold_passes():
    assert passes_gate(_result(total_trades=30)) is True


def test_too_low_a_profit_factor_fails():
    assert passes_gate(_result(profit_factor=1.29)) is False


def test_too_deep_a_drawdown_fails():
    assert passes_gate(_result(max_drawdown=0.16)) is False


def test_exactly_the_drawdown_threshold_passes():
    assert passes_gate(_result(max_drawdown=0.15)) is True


# --- BacktestGateStore: persistence + live_eligible ------------------------

async def test_a_strategy_with_no_stored_result_is_not_live_eligible():
    store = _store()
    assert await store.live_eligible("never-backtested") is False


async def test_recording_a_passing_result_makes_the_strategy_live_eligible():
    store = _store()
    await store.record("volume_surge", _result())
    assert await store.live_eligible("volume_surge") is True


async def test_recording_a_failing_result_keeps_the_strategy_ineligible():
    store = _store()
    await store.record("orb", _result(profit_factor=0.8))
    assert await store.live_eligible("orb") is False


async def test_only_the_most_recent_result_decides_eligibility():
    """A strategy that failed, was improved, and re-tested should become
    eligible -- history is kept, but eligibility follows the latest run."""
    store = _store()
    await store.record("orb", _result(profit_factor=0.8, total_pnl=-1000.0))
    await store.record("orb", _result(profit_factor=1.5, total_pnl=5000.0))

    assert await store.live_eligible("orb") is True


async def test_one_strategys_result_does_not_affect_another():
    store = _store()
    await store.record("volume_surge", _result())
    assert await store.live_eligible("orb") is False


async def test_latest_returns_the_stored_verdict_and_result():
    store = _store()
    await store.record("volume_surge", _result(total_trades=40))

    latest = await store.latest("volume_surge")
    assert latest is not None
    assert latest["passed"] is True
    assert latest["result"]["total_trades"] == 40
