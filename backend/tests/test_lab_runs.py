"""backend.lab.runs: reproducible run records are best-effort and never break a simulator."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.lab import runs
from backend.lab.assumptions import DAILY, DEFAULT
from backend.lab.runs import LabRunStore, fingerprint
from backend.lab.splits import Fold

W = (date(2020, 1, 1), date(2021, 1, 1))
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
RESULT = SimpleNamespace(total_trades=0, profit_factor=0.0, max_drawdown=0.0, total_pnl=0.0, trades=[])


@pytest.mark.asyncio
async def test_record_then_get_round_trips_and_list_is_newest_first():
    store = LabRunStore(AsyncMongoMockClient()["t"])
    await store.ensure_indexes()
    fold = Fold(2021, date(2018, 1, 1), date(2021, 1, 1), date(2021, 1, 1), date(2022, 1, 1))
    a = await store.record(kind="factor", name="x", config={"k": 1}, execution=DAILY, window=W,
                           fingerprint="fp", folds=[fold], metrics={"sharpe": 1.0}, user_id="u")
    b = await store.record(kind="engine", name="y", config={}, execution=DEFAULT, window=W,
                           fingerprint=None, folds=[], metrics={})
    got = await store.get(a)
    assert got["kind"] == "factor" and got["execution"] == {"slippage_bps": 10.0, "fill": "next_close"}
    assert got["window"] == ["2020-01-01", "2021-01-01"] and got["folds"][0]["year"] == 2021
    assert got["folds"][0]["test_start"] == "2021-01-01" and got["user_id"] == "u" and got["code_sha"]
    assert [r["id"] for r in await store.list()] == [b, a]
    assert [r["id"] for r in await store.list(kind="factor")] == [a]
    assert await store.get("nope") is None


def test_fingerprint_ignores_column_order_and_sees_one_close():
    a = pd.DataFrame({"X": [1.0, 2.0], "Y": [3.0, 4.0]}, index=pd.bdate_range("2024-01-01", periods=2))
    assert fingerprint(a) == fingerprint(a[["Y", "X"]])
    b = a.copy()
    b.iloc[1, 0] = 2.0001
    assert fingerprint(a) != fingerprint(b)


def test_code_sha_prefers_env_then_falls_back(monkeypatch):
    runs.code_sha.cache_clear()
    monkeypatch.setenv("GIT_SHA", "abc")
    assert runs.code_sha() == "abc"
    runs.code_sha.cache_clear()
    monkeypatch.delenv("GIT_SHA")
    with patch("backend.lab.runs.subprocess.run", side_effect=OSError):
        assert runs.code_sha() == "unknown"
    runs.code_sha.cache_clear()


class _Broken:
    def __getitem__(self, _):
        raise RuntimeError("mongo down")


@pytest.mark.asyncio
async def test_record_failure_never_raises():
    assert await LabRunStore(_Broken()).record(kind="factor", name="x", config={}, execution=DEFAULT,
                                               window=W, fingerprint=None, folds=[], metrics={}) is None


@pytest.mark.asyncio
async def test_gate_run_record_failure_is_swallowed():
    from backend.risk import gate_backtest

    with patch.object(LabRunStore, "record", side_effect=RuntimeError("boom")):
        await gate_backtest._record_run(AsyncMongoMockClient()["t"], "s", RESULT, 1e6, NOW)


@pytest.mark.asyncio
async def test_gate_backtest_records_an_engine_run():
    from backend.risk import gate_backtest

    db = AsyncMongoMockClient()["t"]
    await gate_backtest._record_run(db, "s", RESULT, 1e6, NOW)
    [run] = await LabRunStore(db).list(kind="engine", name="s")
    assert run["metrics"]["trades"] == 0 and "summary" in run["metrics"] and run["fingerprint"] is None
