"""The daily post-close pass.

Tested through run_daily_jobs with an explicit `now`, so nothing here waits
on a clock. The scheduling arithmetic is tested separately -- getting "next
16:00 IST" wrong by a day is the kind of bug that only shows up as silence.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend import scheduler
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.prefs import PrefsStore
from backend.suggestions.store import SuggestionStore


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


# ---------------------------------------------------------------------------
# Scheduling arithmetic
# ---------------------------------------------------------------------------

def test_next_run_is_later_today_when_the_hour_has_not_passed():
    now = datetime(2024, 1, 15, 9, 0, tzinfo=IST)
    assert scheduler.seconds_until_next_run(now) == 7 * 3600


def test_next_run_rolls_to_tomorrow_once_the_hour_has_passed():
    now = datetime(2024, 1, 15, 16, 30, tzinfo=IST)
    assert scheduler.seconds_until_next_run(now) == pytest.approx(23.5 * 3600)


def test_scheduling_is_computed_in_ist_not_utc():
    """23:00 IST is 17:30 UTC the same day; a UTC-based calculation would
    think 16:00 was still seven hours away instead of tomorrow."""
    now = datetime(2024, 1, 15, 23, 0, tzinfo=IST)
    assert scheduler.seconds_until_next_run(now) == pytest.approx(17 * 3600)


# ---------------------------------------------------------------------------
# The pass itself
# ---------------------------------------------------------------------------

async def _add_user(mongo, user_id: str) -> None:
    await mongo["users"].insert_one({"id": user_id, "google_sub": user_id, "email": f"{user_id}@x.com",
                                     "name": user_id, "picture": None,
                                     "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc)})


@pytest.mark.asyncio
async def test_pass_scans_for_each_enabled_user(mongo, monkeypatch):
    await _add_user(mongo, "alice")
    await _add_user(mongo, "bob")
    scanned = []

    async def fake_scan(db, user_id, universe, **kwargs):
        scanned.append((user_id, kwargs["source"]))
        return []

    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    result = await scheduler.run_daily_jobs(mongo, now=datetime(2024, 1, 15, tzinfo=timezone.utc))

    assert sorted(scanned) == [("alice", "scheduler"), ("bob", "scheduler")]
    assert result["users"] == 2


@pytest.mark.asyncio
async def test_pass_skips_users_who_turned_scanning_off(mongo, monkeypatch):
    await _add_user(mongo, "alice")
    await _add_user(mongo, "bob")
    await PrefsStore(mongo).update("bob", {"scan_enabled": False})
    scanned = []

    async def fake_scan(db, user_id, universe, **kwargs):
        scanned.append(user_id)
        return []

    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    await scheduler.run_daily_jobs(mongo, now=datetime(2024, 1, 15, tzinfo=timezone.utc))

    assert scanned == ["alice"]


@pytest.mark.asyncio
async def test_one_users_failure_does_not_stop_the_others(mongo, monkeypatch):
    await _add_user(mongo, "alice")
    await _add_user(mongo, "bob")

    async def fake_scan(db, user_id, universe, **kwargs):
        if user_id == "alice":
            raise RuntimeError("yfinance said no")
        return []

    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    result = await scheduler.run_daily_jobs(mongo, now=datetime(2024, 1, 15, tzinfo=timezone.utc))

    assert result["users"] == 1


@pytest.mark.asyncio
async def test_pass_expires_stale_pending_suggestions(mongo, monkeypatch):
    now = datetime(2024, 1, 15, tzinfo=timezone.utc)
    store = SuggestionStore(mongo)
    await mongo["suggestions"].insert_one({
        "id": "s1", "user_id": "alice", "symbol": "RELIANCE", "mode": "LONGTERM",
        "status": "PENDING", "created_at": now - timedelta(days=9),
        "expires_at": now - timedelta(days=6),
    })

    async def fake_scan(db, user_id, universe, **kwargs):
        return []

    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    result = await scheduler.run_daily_jobs(mongo, now=now)

    assert result["expired"] == 1
    assert (await store.get("alice", "s1"))["status"] == "EXPIRED"


@pytest.mark.asyncio
async def test_new_suggestions_get_a_thesis(mongo, monkeypatch):
    await _add_user(mongo, "alice")
    created = [{"id": "s1", "symbol": "RELIANCE"}]

    async def fake_scan(db, user_id, universe, **kwargs):
        await mongo["suggestions"].insert_one({
            "id": "s1", "user_id": "alice", "symbol": "RELIANCE", "mode": "LONGTERM",
            "status": "PENDING", "ai_thesis": None,
        })
        return created

    class _Agent:
        async def run(self, symbol):
            return type("R", (), {"thesis": f"{symbol} is compounding.", "analyst_summary": ""})()

    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)
    monkeypatch.setattr(
        scheduler, "attach_theses",
        lambda db, user_id, suggestions: __import__(
            "backend.suggestions.thesis", fromlist=["attach_theses"]
        ).attach_theses(db, user_id, suggestions, agent=_Agent()),
    )

    await scheduler.run_daily_jobs(mongo, now=datetime(2024, 1, 15, tzinfo=timezone.utc))

    assert (await SuggestionStore(mongo).get("alice", "s1"))["ai_thesis"] == "RELIANCE is compounding."


# ---------------------------------------------------------------------------
# close_expired_option_positions (Phase 5b)
# ---------------------------------------------------------------------------

async def _seed_option_position(mongo, tradingsymbol: str, expiry: datetime, strike: float) -> None:
    await _add_user(mongo, "alice")
    master = InstrumentMaster(mongo)
    await master.upsert_many([Instrument(
        exchange="NFO", tradingsymbol=tradingsymbol, name="RELIANCE",
        instrument_token=1, exchange_token=1, instrument_type="PE", segment="NFO-OPT",
        lot_size=250, tick_size=0.05, expiry=expiry, strike=strike,
    )])
    ledger = LedgerStore(mongo, user_id="alice")
    await ledger.positions.insert_one({
        "user_id": "alice", "run_id": None, "symbol": tradingsymbol,
        "quantity": -250.0, "avg_price": 45.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0,
    })


@pytest.mark.asyncio
async def test_closes_an_expired_otm_position_worthless(mongo):
    # Instrument.expiry is stored/read as a NAIVE UTC datetime -- see
    # backend/instruments/kite_source.py's mapping and
    # backend/instruments/loader.py's own documented note that Motor hands
    # back naive UTC datetimes regardless of what was stored.
    await _seed_option_position(mongo, "RELIANCE24NOV2800PE", datetime(2024, 11, 28), 2800.0)

    async def fake_spot(symbol: str) -> float:
        return 3200.0  # far OTM: spot >> strike for a put

    closed = await scheduler.close_expired_option_positions(
        mongo, now=datetime(2024, 12, 1, tzinfo=timezone.utc), spot_lookup=fake_spot,
    )

    assert closed == 1
    positions = await LedgerStore(mongo, user_id="alice").get_open_positions()
    assert "RELIANCE24NOV2800PE" not in positions


@pytest.mark.asyncio
async def test_leaves_unexpired_positions_untouched(mongo):
    await _seed_option_position(mongo, "RELIANCE25JAN2800PE", datetime(2025, 1, 30), 2800.0)

    async def fake_spot(symbol: str) -> float:
        return 3200.0

    closed = await scheduler.close_expired_option_positions(
        mongo, now=datetime(2024, 12, 1, tzinfo=timezone.utc), spot_lookup=fake_spot,
    )
    assert closed == 0


# ---------------------------------------------------------------------------
# Analyst verdict refresh (Phase 6)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pass_refreshes_analyst_verdicts_for_curated_symbols(mongo, monkeypatch):
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    refreshed = []

    async def fake_refresh(symbol, redis, **kwargs):
        refreshed.append(symbol)
        return {}
    monkeypatch.setattr(scheduler, "refresh_analyst_verdict", fake_refresh)

    redis = AsyncMock()
    result = await scheduler.run_daily_jobs(mongo, redis=redis, now=datetime(2024, 1, 15, tzinfo=timezone.utc))

    from backend.options.resolver import STRIKE_INTERVALS
    assert set(refreshed) == set(STRIKE_INTERVALS)
    assert result["verdicts_refreshed"] == len(STRIKE_INTERVALS)


@pytest.mark.asyncio
async def test_pass_skips_analyst_verdict_refresh_without_redis(mongo, monkeypatch):
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    called = []

    async def fake_refresh(symbol, redis, **kwargs):
        called.append(symbol)
        return {}
    monkeypatch.setattr(scheduler, "refresh_analyst_verdict", fake_refresh)

    result = await scheduler.run_daily_jobs(mongo, redis=None, now=datetime(2024, 1, 15, tzinfo=timezone.utc))

    assert called == []
    assert result["verdicts_refreshed"] == 0


@pytest.mark.asyncio
async def test_one_symbols_verdict_refresh_failure_does_not_stop_the_others(mongo, monkeypatch):
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    async def flaky_refresh(symbol, redis, **kwargs):
        if symbol == "TCS":
            raise RuntimeError("LLM timeout")
        return {}
    monkeypatch.setattr(scheduler, "refresh_analyst_verdict", flaky_refresh)

    from backend.options.resolver import STRIKE_INTERVALS
    redis = AsyncMock()
    result = await scheduler.run_daily_jobs(mongo, redis=redis, now=datetime(2024, 1, 15, tzinfo=timezone.utc))

    assert result["verdicts_refreshed"] == len(STRIKE_INTERVALS) - 1


# ---------------------------------------------------------------------------
# Distributed lock (Phase 7)
# ---------------------------------------------------------------------------

from unittest.mock import ANY


@pytest.mark.asyncio
async def test_redis_none_always_runs_the_pass_with_no_lock(mongo, monkeypatch):
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    result = await scheduler._run_locked(mongo, None)

    assert result is not None
    assert result["users"] == 0


@pytest.mark.asyncio
async def test_a_second_worker_skips_the_pass_while_the_lock_is_held(mongo, monkeypatch):
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=None)  # NX failed: someone else holds it

    result = await scheduler._run_locked(mongo, redis)

    assert result is None
    redis.set.assert_awaited_once_with(scheduler.LOCK_KEY, ANY, nx=True, px=scheduler.LOCK_TTL_MS)


@pytest.mark.asyncio
async def test_the_lock_is_released_after_the_pass_completes(mongo, monkeypatch):
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)
    monkeypatch.setattr(scheduler.uuid, "uuid4", lambda: "fixed-token")

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value="fixed-token")

    result = await scheduler._run_locked(mongo, redis)

    assert result is not None
    redis.delete.assert_awaited_once_with(scheduler.LOCK_KEY)


@pytest.mark.asyncio
async def test_a_worker_never_releases_a_lock_it_no_longer_owns(mongo, monkeypatch):
    """The TTL can expire and another worker can acquire the lock before this
    worker's release runs; the release must check ownership first."""
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)
    monkeypatch.setattr(scheduler.uuid, "uuid4", lambda: "fixed-token")

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value="someone-elses-token")

    await scheduler._run_locked(mongo, redis)

    redis.delete.assert_not_awaited()
