import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.builder import draft, store
from backend.learning.library import catalog
from backend.strategies.built import set_active
from backend.strategies.registry import build_default_strategies

EX = {
    "setup": {"gap": {"direction": "down", "min_pct": 1.0}},
    "filters": {"time_window": {"start": "09:30", "end": "14:45"}},
    "side": "long", "stop": {"atr_multiple": 1.0}, "target": {"r_multiple": 2.0},
}


def doc(slug, status="active", **kw):
    return {"slug": slug, "spec": EX, "thesis": "t", "status": status, "drafted_at": slug, **kw}


@pytest.fixture(autouse=True)
def _reset_active():
    set_active([])
    yield
    set_active([])


def test_registry_loads_global_plus_own_only():
    set_active([{"slug": "g", "spec": EX}, {"slug": "a", "spec": EX, "owner_id": "A"},
                {"slug": "b", "spec": EX, "owner_id": "B"}])
    names = lambda uid: {s.spec.name for s in build_default_strategies(universe=["X"], user_id=uid)
                         if s.spec.name.startswith("built:")}
    assert names("A") == {"built:g", "built:a"} and names(None) == {"built:g"}


@pytest.mark.asyncio
async def test_trial_sharpes_per_owner():
    db = AsyncMongoMockClient()["t"]
    for d in (doc("g1", sharpe=1.0), doc("g2", sharpe=2.0), doc("a1", sharpe=3.0, owner_id="A")):
        await store.insert(db, d)
    assert len(await store.trial_sharpes(db)) == 2
    assert len(await store.trial_sharpes(db, "A")) == 1


@pytest.mark.asyncio
async def test_visible_is_global_plus_own():
    db = AsyncMongoMockClient()["t"]
    for d in (doc("g"), doc("a", owner_id="A"), doc("b", owner_id="B")):
        await store.insert(db, d)
    assert [d["slug"] for d in await store.visible(db, "A")] == ["g", "a"]  # newest first: drafted_at desc


@pytest.mark.asyncio
async def test_catalog_lists_own_built_only():
    db = AsyncMongoMockClient()["t"]
    for d in (doc("g"), doc("a", owner_id="A"), doc("b", owner_id="B")):
        await store.insert(db, d)
    names = {c["name"] for c in await catalog(db, "B", [])}
    assert "built:b" in names and "built:g" in names and "built:a" not in names


@pytest.mark.asyncio
async def test_make_room_ignores_user_strategies():
    db = AsyncMongoMockClient()["t"]
    for i in range(5):
        await store.insert(db, doc(f"u{i}", owner_id="A"))
    for i in range(draft.MAX_ACTIVE - 1):
        await store.insert(db, doc(f"ai{i}"))
    assert await draft._make_room(db) == []
