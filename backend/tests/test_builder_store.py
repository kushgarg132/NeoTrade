from datetime import date, timedelta

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.builder import store
from backend.learning.library import catalog
from backend.learning.retune import variant
from backend.strategies.built import BlockStrategy, active, set_active

SPEC = {
    "setup": {"gap": {"direction": "down", "min_pct": 1.0}},
    "filters": {"time_window": {"start": "09:30", "end": "14:45"}},
    "side": "long", "stop": {"atr_multiple": 1.0}, "target": {"r_multiple": 2.0},
}


def doc(slug, status, **kw):
    return {"slug": slug, "spec": SPEC, "thesis": "t", "status": status, "drafted_at": slug, **kw}


@pytest.fixture(autouse=True)
def _reset_active():
    set_active([])
    yield
    set_active([])


@pytest.mark.asyncio
async def test_refresh_loads_only_active():
    db = AsyncMongoMockClient()["t"]
    for slug, status in (("a", "active"), ("b", "testing"), ("c", "rejected"), ("d", "retired")):
        await store.insert(db, doc(slug, status))
    assert [d["slug"] for d in await store.refresh(db)] == ["a"]
    assert [d["slug"] for d in active()] == ["a"]
    await store.set_status(db, "a", "retired", "stopped working")
    await store.refresh(db)
    assert active() == []
    assert (await store.all_drafts(db))[0]["slug"] == "d"  # newest first


@pytest.mark.asyncio
async def test_trial_sharpes_counts_every_test_but_the_excluded_draft():
    db = AsyncMongoMockClient()["t"]
    await store.insert(db, doc("a", "testing", sharpe=9.0))  # re-queued: its earlier test still counts
    await store.insert(db, doc("b", "rejected", sharpe=0.1, trial_history=[0.2, float("nan"), 0.1]))
    await store.insert(db, doc("c", "active", sharpe=0.5))
    await store.insert(db, doc("d", "testing"))  # never tested
    assert sorted(await store.trial_sharpes(db)) == [0.1, 0.2, 0.5, 9.0]
    assert sorted(await store.trial_sharpes(db, exclude="a")) == [0.1, 0.2, 0.5]


@pytest.mark.asyncio
async def test_catalog_lists_active_built_strategy():
    db = AsyncMongoMockClient()["t"]
    await store.insert(db, doc("gdvr", "active"))
    names = [c["name"] for c in await catalog(db, "u1", [])]
    assert "built:gdvr" in names


@pytest.mark.asyncio
async def test_regime_of_without_bars_is_none():
    assert (await store.regime_of(AsyncMongoMockClient()["t"]))(__import__("datetime").date(2026, 1, 5)) is None


def test_variant_rebuilds_block_strategy_with_new_params():
    regime = lambda d: "risk_on"
    s = BlockStrategy("gdvr", SPEC, ["X"], {1: "X"}, regime_of=regime, sector_of={"X": "IT"}, thesis="why")
    key = "setup.gap.min_pct"
    v = variant(s, ["X"], {1: "X"}, {key: 1.5})
    assert isinstance(v, BlockStrategy) and v.slug == "gdvr" and v.thesis == "why"
    assert v.p[key] == 1.5 and s.p[key] == 1.0
    assert v._regime_of is regime and v._sector_of == {"X": "IT"}
    assert v.base_spec == s.base_spec


class _Boom:
    def __getitem__(self, name):
        raise RuntimeError("db down")


@pytest.mark.asyncio
async def test_refresh_failure_keeps_cache_and_returns_empty():
    set_active([{"slug": "keep", "spec": SPEC}])
    assert await store.refresh(_Boom()) == []
    assert [d["slug"] for d in active()] == ["keep"]


@pytest.mark.asyncio
async def test_refresh_skips_malformed_docs():
    db = AsyncMongoMockClient()["t"]
    await db[store.COLLECTION].insert_many([
        {"status": "active", "spec": SPEC}, {"status": "active", "slug": "x"}, doc("ok", "active")])
    assert [d["slug"] for d in await store.refresh(db)] == ["ok"]


@pytest.mark.asyncio
async def test_regime_of_failure_gives_none_lookup():
    assert (await store.regime_of(_Boom()))(date(2026, 1, 5)) is None


@pytest.mark.asyncio
async def test_regime_of_risk_on_for_rising_nifty(monkeypatch):
    start = date(2025, 1, 1)
    rows = [(start + timedelta(days=i), 100.0 + i) for i in range(250)]

    async def closes(db, since):
        return rows
    monkeypatch.setattr(store.bars, "nifty_closes", closes)
    assert (await store.regime_of(None))(start + timedelta(days=250)) == "risk_on"


@pytest.mark.asyncio
async def test_trial_sharpes_drops_non_finite():
    db = AsyncMongoMockClient()["t"]
    for slug, s in (("a", float("nan")), ("b", float("inf")), ("c", 0.2), ("d", None)):
        await store.insert(db, doc(slug, "rejected", sharpe=s))
    assert await store.trial_sharpes(db) == [0.2]


@pytest.mark.asyncio
async def test_regime_of_covers_a_year_long_backtest(monkeypatch):
    today = store.bars.today_ist()
    asked = []

    async def closes(db, since):
        asked.append(since)
        return [(since + timedelta(days=i), 100.0 + i) for i in range((today - since).days)]
    monkeypatch.setattr(store.bars, "nifty_closes", closes)
    assert (await store.regime_of(None))(today - timedelta(days=365)) is not None
    assert asked == [today - timedelta(days=800)]


@pytest.mark.asyncio
async def test_ensure_indexes_makes_slug_and_week_unique():
    from pymongo.errors import DuplicateKeyError

    db = AsyncMongoMockClient()["t"]
    await store.ensure_indexes(db)
    await store.insert(db, doc("a", "testing"))
    with pytest.raises(DuplicateKeyError):
        await store.insert(db, doc("a", "rejected"))
    await db[store.RUNS].insert_one({"week": "2026-W41"})
    with pytest.raises(DuplicateKeyError):
        await db[store.RUNS].insert_one({"week": "2026-W41"})
