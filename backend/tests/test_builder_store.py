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
async def test_trial_sharpes_excludes_testing():
    db = AsyncMongoMockClient()["t"]
    await store.insert(db, doc("a", "testing", sharpe=9.0))
    await store.insert(db, doc("b", "rejected", sharpe=0.1))
    await store.insert(db, doc("c", "active", sharpe=0.5))
    assert sorted(await store.trial_sharpes(db)) == [0.1, 0.5]


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
