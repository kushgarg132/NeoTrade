"""refresh_instruments_from_adapter / refresh_from_free_public_sources: the
bundled seed file (~130 large-caps) is a floor, not the real universe --
these are what actually expand the instrument master, and neither must ever
raise regardless of why it can't (no session, expired session, database
down, NSE/BSE unreachable).

The adapter refresh takes any BrokerAdapter (Kite, Upstox, Angel One --
whichever the connecting user just connected) rather than a Kite-specific
session, since credentials are per-user and per-broker."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from backend.brokers.protocol import BrokerSessionState
from backend.instruments import loader


def _fake_master(meta_doc=None):
    """A master whose collection.database["instrument_meta"] behaves like a
    real Mongo collection for the last-refreshed marker refresh_from_free_public_sources
    reads/writes, plus an AsyncMock upsert_many for refresh_instruments to call."""
    meta = MagicMock()
    meta.find_one = AsyncMock(return_value=meta_doc)
    meta.update_one = AsyncMock()
    master = MagicMock()
    master.collection.database.__getitem__.return_value = meta
    master.upsert_many = AsyncMock(side_effect=[3, 1, 2])  # NSE, NSE ETF, BSE
    return master, meta


async def test_no_op_when_the_adapter_is_not_active():
    fake_adapter = MagicMock()
    fake_adapter.state = AsyncMock(return_value=BrokerSessionState.NEEDS_LOGIN)

    result = await loader.refresh_instruments_from_adapter(fake_adapter)

    assert result == 0


async def test_refreshes_both_nse_and_bse_when_active(monkeypatch):
    monkeypatch.setattr("backend.database.db.db", MagicMock())

    fake_adapter = MagicMock()
    fake_adapter.state = AsyncMock(return_value=BrokerSessionState.ACTIVE)
    fake_adapter.instruments = AsyncMock(return_value=["stub"] * 5)

    monkeypatch.setattr(loader, "refresh_instruments", AsyncMock(return_value=1847))

    result = await loader.refresh_instruments_from_adapter(fake_adapter)

    assert result == 1847
    fake_adapter.instruments.assert_not_called()  # refresh_instruments itself is mocked out


async def test_never_raises_and_returns_zero_on_any_failure():
    fake_adapter = MagicMock()
    fake_adapter.state = AsyncMock(side_effect=RuntimeError("redis is down"))

    result = await loader.refresh_instruments_from_adapter(fake_adapter)

    assert result == 0


async def test_free_sources_sum_counts_from_both_exchanges(monkeypatch):
    class _FakeNse:  # also stands in for the NSE ETF list (constructed with its URL)
        def __init__(self, url=None):
            pass

        async def fetch(self):
            return ["nse-stub"] * 3

    class _FakeBse:
        async def fetch(self):
            return ["bse-stub"] * 2

    monkeypatch.setattr("backend.instruments.free_source.NseEquityListSource", _FakeNse)
    monkeypatch.setattr("backend.instruments.free_source.BseEquityListSource", _FakeBse)

    master, meta = _fake_master()

    result = await loader.refresh_from_free_public_sources(master)

    assert result == 6
    meta.update_one.assert_awaited_once()  # marker recorded so the next run can skip


async def test_free_sources_one_exchange_failing_does_not_stop_the_other(monkeypatch):
    class _FakeNse:  # also stands in for the NSE ETF list (constructed with its URL)
        def __init__(self, url=None):
            pass

        async def fetch(self):
            raise RuntimeError("NSE blocked this IP")

    class _FakeBse:
        async def fetch(self):
            return ["bse-stub"]

    monkeypatch.setattr("backend.instruments.free_source.NseEquityListSource", _FakeNse)
    monkeypatch.setattr("backend.instruments.free_source.BseEquityListSource", _FakeBse)

    master, _meta = _fake_master()
    master.upsert_many = AsyncMock(return_value=1)

    result = await loader.refresh_from_free_public_sources(master)

    assert result == 1


async def test_free_sources_skip_when_refreshed_recently(monkeypatch):
    master, meta = _fake_master(
        meta_doc={"_id": "free_source_refresh", "last_refreshed_at": datetime.now(timezone.utc) - timedelta(hours=1)}
    )
    fetch_spy = AsyncMock()
    monkeypatch.setattr(loader, "refresh_instruments", fetch_spy)

    result = await loader.refresh_from_free_public_sources(master)

    assert result == 0
    fetch_spy.assert_not_called()
    meta.update_one.assert_not_called()


async def test_free_sources_refresh_again_once_the_marker_is_stale(monkeypatch):
    class _FakeNse:  # also stands in for the NSE ETF list (constructed with its URL)
        def __init__(self, url=None):
            pass

        async def fetch(self):
            return ["nse-stub"]

    class _FakeBse:
        async def fetch(self):
            return ["bse-stub"]

    monkeypatch.setattr("backend.instruments.free_source.NseEquityListSource", _FakeNse)
    monkeypatch.setattr("backend.instruments.free_source.BseEquityListSource", _FakeBse)

    master, meta = _fake_master(
        meta_doc={"_id": "free_source_refresh", "last_refreshed_at": datetime.now(timezone.utc) - timedelta(hours=48)}
    )
    master.upsert_many = AsyncMock(return_value=1)

    result = await loader.refresh_from_free_public_sources(master)

    assert result == 3
    meta.update_one.assert_awaited_once()
