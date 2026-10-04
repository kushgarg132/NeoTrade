"""backend.learning.retune: a strategy's thresholds change only when a
variant chosen on the earlier part of the window also wins on the later,
unseen part, and survives the deflated Sharpe over every variant tried."""

import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.learning import retune
from backend.learning.retune import current_params, retune_strategy, variants

START = datetime(2023, 1, 2, tzinfo=timezone.utc)
SPLIT = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _result(start, end, daily_mean, n_days=None, seed=0):
    """A fake BacktestResult: one closing trade per weekday, P&L drawn
    around `daily_mean` rupees."""
    rng = random.Random(seed)
    trades, day = [], start
    while day < end and (n_days is None or len(trades) < n_days):
        if day.weekday() < 5:
            pnl = daily_mean + rng.gauss(0, 2000)
            trades.append({"timestamp": day.isoformat(), "realized_pnl": pnl, "net_pnl": pnl})
        day += timedelta(days=1)
    return SimpleNamespace(trades=trades, total_trades=len(trades), total_pnl=sum(t["net_pnl"] for t in trades),
                           sharpe_ratio=daily_mean)


def _backtester(train_means: dict, test_means: dict, train_days=None):
    """mean per volume_mult in-sample and out-of-sample."""
    calls = []

    async def backtest(params, start, end):
        calls.append((params["volume_mult"], start))
        means = train_means if start < SPLIT - timedelta(days=retune.WARMUP_DAYS["1d"]) else test_means
        return _result(start, end, means[params["volume_mult"]], n_days=train_days,
                       seed=int(params["volume_mult"] * 10))
    backtest.calls = calls
    return backtest


class _Strategy:
    PARAMS = {"volume_mult": 3.0}
    GRID = {"volume_mult": [2.0, 3.0, 4.0]}
    spec = SimpleNamespace(name="volume_surge", timeframe="1d")


def test_variants_are_every_combination_of_the_grid():
    assert len(variants({"a": [1, 2], "b": [1, 2, 3]})) == 6
    assert {"a": 2, "b": 3} in variants({"a": [1, 2], "b": [1, 2, 3]})


@pytest.mark.asyncio
async def test_a_variant_that_wins_in_and_out_of_sample_is_accepted():
    bt = _backtester({2.0: -100, 3.0: 100, 4.0: 900}, {2.0: 0, 3.0: 50, 4.0: 900})
    doc = await retune_strategy(_Strategy, bt, {"volume_mult": 3.0}, START, SPLIT, END, past_trials=[])
    assert doc["accepted"] and doc["params"] == {"volume_mult": 4.0}
    assert doc["dsr"] >= retune.MIN_DSR and doc["trials"] == 3


@pytest.mark.asyncio
async def test_a_variant_that_only_wins_in_sample_is_rejected():
    bt = _backtester({2.0: -100, 3.0: 100, 4.0: 900}, {2.0: 0, 3.0: 300, 4.0: -200})
    doc = await retune_strategy(_Strategy, bt, {"volume_mult": 3.0}, START, SPLIT, END, past_trials=[])
    assert not doc["accepted"] and doc["params"] == {"volume_mult": 4.0}
    assert "out of sample" in doc["reason"]


@pytest.mark.asyncio
async def test_a_weak_out_of_sample_edge_fails_the_deflated_sharpe():
    bt = _backtester({2.0: -100, 3.0: 100, 4.0: 900}, {2.0: 0, 3.0: -50, 4.0: 30})
    many_tries = [0.3, -0.2, 0.25, 0.1, -0.3] * 20
    doc = await retune_strategy(_Strategy, bt, {"volume_mult": 3.0}, START, SPLIT, END, past_trials=many_tries)
    assert not doc["accepted"] and "deflated Sharpe" in doc["reason"]
    assert doc["trials"] == 103


@pytest.mark.asyncio
async def test_no_change_when_the_current_params_are_still_best():
    bt = _backtester({2.0: -100, 3.0: 900, 4.0: 100}, {})
    doc = await retune_strategy(_Strategy, bt, {"volume_mult": 3.0}, START, SPLIT, END, past_trials=[])
    assert not doc["accepted"] and doc["reason"] == "current params are still best in sample"
    assert len(bt.calls) == 3  # no out-of-sample run needed


@pytest.mark.asyncio
async def test_variants_with_too_few_trades_cannot_be_chosen():
    bt = _backtester({2.0: 100, 3.0: 100, 4.0: 900}, {}, train_days=retune.MIN_TRAIN_TRADES - 1)
    doc = await retune_strategy(_Strategy, bt, {"volume_mult": 3.0}, START, SPLIT, END, past_trials=[])
    assert not doc["accepted"] and "trades" in doc["reason"]


@pytest.mark.asyncio
async def test_the_out_of_sample_run_starts_early_enough_to_warm_up():
    bt = _backtester({2.0: -100, 3.0: 100, 4.0: 900}, {2.0: 0, 3.0: 50, 4.0: 900})
    await retune_strategy(_Strategy, bt, {"volume_mult": 3.0}, START, SPLIT, END, past_trials=[])
    test_starts = {start for _, start in bt.calls if start > START}
    assert test_starts == {SPLIT - timedelta(days=retune.WARMUP_DAYS["1d"])}


@pytest.mark.asyncio
async def test_current_params_are_the_latest_accepted_per_strategy():
    db = AsyncMongoMockClient()["t"]
    await db["strategy_retunes"].insert_many([
        {"strategy": "volume_surge", "accepted": True, "params": {"volume_mult": 4.0}, "at": START},
        {"strategy": "volume_surge", "accepted": True, "params": {"volume_mult": 5.0}, "at": SPLIT},
        {"strategy": "volume_surge", "accepted": False, "params": {"volume_mult": 2.0}, "at": END},
    ])
    assert await current_params(db) == {"volume_surge": {"volume_mult": 5.0}}


@pytest.mark.asyncio
async def test_the_daily_pass_starts_one_retune_a_month(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    started = []

    async def spawn():
        started.append(1)
    monkeypatch.setattr(retune, "spawn", spawn)
    now = datetime(2026, 11, 2, 11, tzinfo=timezone.utc)
    assert await retune.start_if_due(db, now) is True
    assert await retune.start_if_due(db, now + timedelta(days=1)) is False
    assert await retune.start_if_due(db, now + timedelta(days=30)) is True
    assert len(started) == 2


@pytest.mark.asyncio
async def test_run_all_retunes_the_daily_strategies_on_real_backtests(monkeypatch):
    """Wiring only: real strategies and run_backtest over a short synthetic
    history, one fetch per symbol, one record per daily strategy."""
    from backend.components.quant import indian_stocks
    from backend.components.shared.models import PriceCandle
    from backend.instruments.master import InstrumentMaster
    from backend.instruments.models import Instrument

    db = AsyncMongoMockClient()["t"]
    await InstrumentMaster(db).upsert_many([Instrument(
        exchange="NSE", tradingsymbol="TEST", name="Test", instrument_token=42, exchange_token=42,
        instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)])
    monkeypatch.setattr(indian_stocks, "ALL_SCAN_STOCKS", ["TEST"])
    monkeypatch.setattr(retune, "WINDOW_DAYS", {"1d": 150})
    monkeypatch.setattr(retune, "WARMUP_DAYS", {"1d": 60})
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    rng = random.Random(1)
    close, candles = 100.0, []
    for i in range(170):
        close *= 1 + rng.gauss(0.001, 0.02)
        candles.append(PriceCandle(symbol="TEST", timestamp=now - timedelta(days=169 - i), open=close,
                                   high=close * 1.01, low=close * 0.99, close=close, volume=1000 + rng.random() * 3000))
    fetches = []

    class _Provider:
        async def history(self, instrument, interval, period):
            fetches.append(period)
            return candles

        async def quote(self, instrument):
            return {}

    docs = await retune.run_all(db, _Provider(), now)
    assert sorted(d["strategy"] for d in docs) == ["macd_crossover", "mean_reversion", "technical_breakout"]
    assert all(not d["accepted"] and not d["reason"].startswith("failed") for d in docs)
    assert await db["strategy_retunes"].count_documents({}) == 3
    assert len(fetches) == len(set(fetches))  # memoised: each period fetched once
