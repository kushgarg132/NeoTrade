"""backend/routers/trading.py:
- start_background_run/stop_background_run: the actual asyncio.Task
  bookkeeping /trading/start and /trading/stop rely on -- proven directly
  against a feed that would otherwise run forever, with a timeout so a
  regression here fails fast instead of hanging the test suite.
- GET /trading/positions, /trading/fills, /trading/equity: route-level via
  FastAPI TestClient against a seeded LedgerStore (mongomock_motor).
- POST /trading/start + /trading/stop: full route round-trip with
  InstrumentMaster/YFinanceProvider/db monkeypatched to fakes, proving the
  request returns immediately and stop actually cancels the engine loop.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.broker_credentials import BrokerCredentials
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.core.models import Fill, Position, Side
from backend.engine.persistence import LedgerStore
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.routers import trading
from backend.runs import RunStore

_USER = User(
    id="u1", google_sub="sub-1", email="u1@example.com", name="U One",
    picture=None, created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
)


# ---------------------------------------------------------------------------
# start_background_run / stop_background_run
# ---------------------------------------------------------------------------

async def _forever() -> None:
    """Never returns on its own -- like the engine loop against a live
    feed -- so cancellation is the only way it ends."""
    while True:
        await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_start_returns_immediately_and_is_tracked():
    run_id = trading.start_background_run(_forever())
    try:
        assert run_id in trading._RUNS
    finally:
        await asyncio.wait_for(trading.stop_background_run(run_id), timeout=2.0)


@pytest.mark.asyncio
async def test_stop_actually_cancels_the_background_task():
    run_id = trading.start_background_run(_forever())
    stopped = await asyncio.wait_for(trading.stop_background_run(run_id), timeout=2.0)
    assert stopped is True
    assert run_id not in trading._RUNS


@pytest.mark.asyncio
async def test_stop_unknown_run_id_returns_false():
    assert await trading.stop_background_run("no-such-run") is False


import json


@pytest.mark.asyncio
async def test_stop_broadcasts_when_the_run_is_not_local_and_redis_is_configured(monkeypatch):
    from backend.database import db as real_db

    class _FakeRedis:
        def __init__(self):
            self.published = []

        async def publish(self, channel, data):
            self.published.append((channel, data))

    fake_redis = _FakeRedis()
    monkeypatch.setattr(real_db, "redis", fake_redis)

    stopped = await trading.stop_background_run("elsewhere-run")

    assert stopped is True
    assert len(fake_redis.published) == 1
    channel, payload = fake_redis.published[0]
    assert channel == "runs:cancel"
    assert json.loads(payload) == {"run_id": "elsewhere-run"}


@pytest.mark.asyncio
async def test_cancel_broadcast_handler_cancels_a_matching_local_task():
    run_id = trading.start_background_run(_forever())
    try:
        await asyncio.wait_for(trading.handle_cancel_broadcast({"run_id": run_id}), timeout=2.0)
        assert run_id not in trading._RUNS
    finally:
        trading._RUNS.pop(run_id, None)


@pytest.mark.asyncio
async def test_cancel_broadcast_handler_ignores_a_run_id_it_does_not_own():
    await trading.handle_cancel_broadcast({"run_id": "no-such-run"})  # must not raise


# ---------------------------------------------------------------------------
# GET routes against a seeded LedgerStore
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger():
    client = AsyncMongoMockClient()
    return LedgerStore(client["test_db"], user_id="u1")


@pytest.fixture
def client(ledger, monkeypatch):
    async def no_quotes(db, symbols):
        return {}

    monkeypatch.setattr(trading, "mark_prices", no_quotes)

    app = FastAPI()
    app.include_router(trading.router, prefix="/api/v1")
    app.dependency_overrides[trading.get_ledger_store] = lambda: ledger
    return TestClient(app)


def test_get_positions_returns_open_positions(client, ledger):
    asyncio.run(ledger.snapshot_positions({
        "RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=2500.0),
        "TCS": Position(symbol="TCS", quantity=0.0, avg_price=0.0),
    }))

    resp = client.get("/api/v1/trading/positions")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"RELIANCE"}
    assert body["RELIANCE"]["quantity"] == 10.0


def test_ledger_routes_split_paper_from_live(client, ledger):
    """The Paper tab asks for venue=paper and the real-money statement for
    venue=live; neither may see the other's positions, fills or trades."""
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    asyncio.run(ledger.snapshot_positions({
        "RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=2500.0, venue="live"),
        "TCS": Position(symbol="TCS", quantity=5.0, avg_price=3500.0, venue="paper"),
    }))
    for order_id, symbol, venue in (("o1", "RELIANCE", "live"), ("o2", "TCS", "paper")):
        fill = Fill(order_id=order_id, symbol=symbol, side=Side.BUY, quantity=1.0, price=1.0,
                    timestamp=ts, venue=venue)
        asyncio.run(ledger.on_fill(fill, 0.0, Position(symbol=symbol, quantity=1.0, avg_price=1.0)))

    for venue, symbol in (("live", "RELIANCE"), ("paper", "TCS")):
        assert set(client.get("/api/v1/trading/positions", params={"venue": venue}).json()) == {symbol}
        assert [f["symbol"] for f in client.get("/api/v1/trading/fills", params={"venue": venue}).json()] == [symbol]
        assert [t["symbol"] for t in client.get("/api/v1/trading/trades", params={"venue": venue}).json()] == [symbol]
    assert len(client.get("/api/v1/trading/trades").json()) == 2
    assert client.get("/api/v1/trading/trades", params={"venue": "demo"}).status_code == 422


def test_get_fills_optionally_filters_by_symbol(client, ledger):
    asyncio.run(ledger.record_fill(Fill(
        order_id="o1", symbol="RELIANCE", side=Side.BUY, quantity=10.0,
        price=2500.0, timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc), costs=12.5,
    )))
    asyncio.run(ledger.record_fill(Fill(
        order_id="o2", symbol="TCS", side=Side.BUY, quantity=5.0,
        price=3500.0, timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc), costs=8.0,
    )))

    resp = client.get("/api/v1/trading/fills", params={"symbol": "RELIANCE"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "RELIANCE"

    resp_all = client.get("/api/v1/trading/fills")
    assert len(resp_all.json()) == 2


def test_get_equity_reports_realized_pnl_from_open_positions(client, ledger):
    asyncio.run(ledger.snapshot_positions({
        "RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=2500.0, realized_pnl=500.0),
    }))

    resp = client.get("/api/v1/trading/equity")
    assert resp.status_code == 200
    assert resp.json()["equity"] == 500.0  # no live mark price -> zero unrealized movement


# ---------------------------------------------------------------------------
# POST /trading/start + /trading/stop, full route round-trip
# ---------------------------------------------------------------------------

class _FakeMaster:
    def __init__(self, _db) -> None:
        pass

    async def get(self, exchange: str, tradingsymbol: str):
        return Instrument(
            exchange=exchange, tradingsymbol=tradingsymbol, name=tradingsymbol,
            instrument_token=hash(tradingsymbol) % 100000, exchange_token=1,
            instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
        )


class _ForeverQuoteProvider:
    """Never-ending MarketDataProvider stand-in -- PollingLiveFeed's own
    while-True loop already runs forever; this just answers quote() fast so
    the test doesn't wait on a real poll_interval."""

    async def quote(self, instrument):
        return {"last_price": 100.0}

    async def history(self, instrument, interval, period):
        raise NotImplementedError


class _FakeDb:
    # A real (mongomock) database so the router can build its stores;
    # this test never queries them, just proves start/stop.
    db = AsyncMongoMockClient()["test_db"]
    redis = None


# ---------------------------------------------------------------------------
# GET /trading/instruments (wraps InstrumentMaster.search)
# ---------------------------------------------------------------------------

@pytest.fixture
def instruments_client(monkeypatch):
    fake_db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(trading, "db", type("_Db", (), {"db": fake_db})())

    async def _seed():
        master = InstrumentMaster(fake_db)
        await master.upsert_many([
            Instrument(
                exchange="NSE", tradingsymbol="RELIANCE", name="Reliance Industries",
                instrument_token=1, exchange_token=1, instrument_type="EQ",
                segment="NSE", lot_size=1, tick_size=0.05,
            ),
            Instrument(
                exchange="NSE", tradingsymbol="TCS", name="Tata Consultancy Services",
                instrument_token=2, exchange_token=2, instrument_type="EQ",
                segment="NSE", lot_size=1, tick_size=0.05,
            ),
        ])
    asyncio.run(_seed())

    app = FastAPI()
    app.include_router(trading.router, prefix="/api/v1")
    return TestClient(app)


def test_search_instruments_returns_matches(instruments_client):
    resp = instruments_client.get("/api/v1/trading/instruments", params={"q": "RELI"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["tradingsymbol"] == "RELIANCE"


def test_search_instruments_no_matches_returns_empty_list(instruments_client):
    resp = instruments_client.get("/api/v1/trading/instruments", params={"q": "NOSUCHSYMBOL"})
    assert resp.status_code == 200
    assert resp.json() == []


async def _seed_passing_backtest(strategy_name: str) -> None:
    from backend.components.shared.models import BacktestResult
    from backend.risk.backtest_gate import BacktestGateStore

    await BacktestGateStore(_FakeDb.db).record(strategy_name, BacktestResult(
        symbol="RELIANCE", start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
        total_trades=40, win_rate=0.55, profit_factor=1.5, total_pnl=50_000.0,
        max_drawdown=0.10, sharpe_ratio=1.2, trades=[],
    ))


def _no_active_broker_session(monkeypatch):
    """Stubs the registry lookup /trading/start now makes on every call (not
    just INTRADAY) to decide live routing, so tests that don't care about
    broker state don't hit the real (unconnected-in-tests) credential store."""
    from backend.brokers.protocol import BrokerSessionState

    monkeypatch.setattr(
        trading, "get_broker_adapter",
        AsyncMock(return_value=_FakeAdapter(BrokerSessionState.NEEDS_LOGIN)),
    )


def test_start_then_stop_round_trip(monkeypatch):
    monkeypatch.setattr(trading, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(trading, "YFinanceProvider", _ForeverQuoteProvider)
    monkeypatch.setattr(trading, "db", _FakeDb)
    _no_active_broker_session(monkeypatch)
    for name in ("technical_breakout", "mean_reversion", "macd_crossover"):
        asyncio.run(_seed_passing_backtest(name))

    app = FastAPI()
    app.include_router(trading.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[trading.get_run_store] = lambda: RunStore(_FakeDb.db)

    with TestClient(app) as test_client:
        resp = test_client.post("/api/v1/trading/start", json={
            "mode": "LONGTERM", "universe": ["RELIANCE"], "poll_interval_seconds": 0.01,
        })
        assert resp.status_code == 200  # returns immediately, doesn't block on the loop
        run_id = resp.json()["run_id"]
        assert run_id in trading._RUNS

        stop_resp = test_client.post("/api/v1/trading/stop", json={"run_id": run_id})
        assert stop_resp.status_code == 200
        assert stop_resp.json()["stopped"] is True
        assert run_id not in trading._RUNS


# ---------------------------------------------------------------------------
# Feed selection: Kite ticks when a broker session is live, polling otherwise
# ---------------------------------------------------------------------------

def _instruments():
    return [Instrument(
        exchange="NSE", tradingsymbol="RELIANCE", name="Reliance", instrument_token=1,
        exchange_token=1, instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )]


class _Credentials:
    """Stands in for BrokerCredentialStore. `stored=None` is a user who has
    never entered broker credentials, which must still be able to trade."""

    def __init__(self, stored=BrokerCredentials(api_key="ak", api_secret="as")):
        self._stored = stored

    async def get(self, user_id, broker):
        return self._stored


class _FakeAdapter:
    """Stands in for whatever backend.brokers.registry.get_broker_adapter
    returns -- tests care about the state()/ticker_feed() contract, not any
    real broker's implementation."""

    def __init__(self, state, feed=None):
        self._state = state
        self._feed = feed

    async def state(self):
        return self._state

    async def ticker_feed(self, instrument_tokens, timeframe, timeframe_seconds):
        return self._feed


class _StubFeed:
    pass


@pytest.mark.asyncio
async def test_intraday_uses_a_broker_tick_feed_when_the_broker_is_connected(monkeypatch):
    from backend.brokers.protocol import BrokerSessionState

    stub = _StubFeed()
    monkeypatch.setattr(
        trading, "get_broker_adapter",
        AsyncMock(return_value=_FakeAdapter(BrokerSessionState.ACTIVE, feed=stub)),
    )
    monkeypatch.setattr(trading, "db", _FakeDb)

    feed = await trading.build_feed(
        _instruments(), "INTRADAY", 60.0, user_id="alice", credentials=_Credentials(),
    )

    assert feed is stub


@pytest.mark.asyncio
async def test_intraday_falls_back_to_polling_without_a_broker_session(monkeypatch):
    from backend.brokers.protocol import BrokerSessionState
    from backend.data.feeds.polling_live import PollingLiveFeed

    monkeypatch.setattr(
        trading, "get_broker_adapter",
        AsyncMock(return_value=_FakeAdapter(BrokerSessionState.NEEDS_LOGIN)),
    )
    monkeypatch.setattr(trading, "db", _FakeDb)

    feed = await trading.build_feed(
        _instruments(), "INTRADAY", 60.0, user_id="alice", credentials=_Credentials(),
    )

    assert isinstance(feed, PollingLiveFeed)


@pytest.mark.asyncio
async def test_intraday_polls_when_no_connected_broker_supports_streaming(monkeypatch):
    """Active but without streaming support (Upstox/Angel One today) must
    fall back cleanly, not error."""
    from backend.brokers.protocol import BrokerSessionState
    from backend.data.feeds.polling_live import PollingLiveFeed

    monkeypatch.setattr(
        trading, "get_broker_adapter",
        AsyncMock(return_value=_FakeAdapter(BrokerSessionState.ACTIVE, feed=None)),
    )
    monkeypatch.setattr(trading, "db", _FakeDb)

    feed = await trading.build_feed(
        _instruments(), "INTRADAY", 60.0, user_id="alice", credentials=_Credentials(stored=None),
    )

    assert isinstance(feed, PollingLiveFeed)


@pytest.mark.asyncio
async def test_longterm_never_uses_the_tick_feed(monkeypatch):
    """Daily bars have nothing to gain from tick aggregation, and requiring a
    broker login to run a long-term strategy would be a regression."""
    from backend.brokers.protocol import BrokerSessionState
    from backend.data.feeds.polling_live import PollingLiveFeed

    monkeypatch.setattr(
        trading, "get_broker_adapter",
        AsyncMock(return_value=_FakeAdapter(BrokerSessionState.ACTIVE, feed=_StubFeed())),
    )
    monkeypatch.setattr(trading, "db", _FakeDb)

    feed = await trading.build_feed(
        _instruments(), "LONGTERM", 60.0, user_id="alice", credentials=_Credentials(),
    )

    assert isinstance(feed, PollingLiveFeed)


def test_start_excludes_strategies_that_have_not_cleared_the_backtest_gate(monkeypatch):
    """No strategy has a stored backtest result in this test's fresh db --
    the gate must exclude all of them rather than let an unproven strategy
    trade, so the request comes back as "nothing to run", not a silent
    partial start."""
    monkeypatch.setattr(trading, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(trading, "YFinanceProvider", _ForeverQuoteProvider)
    monkeypatch.setattr(trading, "db", type("_Db", (), {"db": AsyncMongoMockClient()["test_db"], "redis": None})())

    app = FastAPI()
    app.include_router(trading.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[trading.get_run_store] = lambda: RunStore(trading.db.db)

    with TestClient(app) as test_client:
        resp = test_client.post("/api/v1/trading/start", json={
            "mode": "LONGTERM", "universe": ["RELIANCE"], "poll_interval_seconds": 0.01,
        })

    assert resp.status_code == 400
    assert "backtest" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_live_eligible_strategies_keeps_only_the_ones_that_passed():
    from backend.components.shared.models import BacktestResult
    from backend.risk.backtest_gate import BacktestGateStore

    class _Strategy:
        def __init__(self, name):
            self.spec = type("_Spec", (), {"name": name})()

    gate = BacktestGateStore(AsyncMongoMockClient()["test_db"])
    await gate.record("technical_breakout", BacktestResult(
        symbol="RELIANCE", start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
        total_trades=40, win_rate=0.55, profit_factor=1.5, total_pnl=50_000.0,
        max_drawdown=0.10, sharpe_ratio=1.2, trades=[],
    ))
    # mean_reversion deliberately left unseeded -- must come back ineligible.

    strategies = [_Strategy("technical_breakout"), _Strategy("mean_reversion")]
    eligible = await trading.live_eligible_strategies(strategies, gate)

    assert [s.spec.name for s in eligible] == ["technical_breakout"]


def _start_app(fake_db=_FakeDb):
    """Same wiring test_start_then_stop_round_trip uses, factored out for the
    live-routing tests below."""
    app = FastAPI()
    app.include_router(trading.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[trading.get_run_store] = lambda: RunStore(fake_db.db)
    return app


def test_start_trading_still_works_with_no_live_strategies_toggled(monkeypatch):
    """Default behavior (empty live_strategies, Task 10's default): every
    strategy runs paper, same as before this feature existed."""
    monkeypatch.setattr(trading, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(trading, "YFinanceProvider", _ForeverQuoteProvider)
    monkeypatch.setattr(trading, "db", _FakeDb)
    _no_active_broker_session(monkeypatch)
    for name in ("technical_breakout", "mean_reversion", "macd_crossover"):
        asyncio.run(_seed_passing_backtest(name))

    with TestClient(_start_app()) as test_client:
        resp = test_client.post("/api/v1/trading/start", json={
            "mode": "LONGTERM", "universe": ["RELIANCE"], "poll_interval_seconds": 0.01,
        })
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]

        stop_resp = test_client.post("/api/v1/trading/stop", json={"run_id": run_id})
        assert stop_resp.json()["stopped"] is True


def test_start_trading_no_longer_501s_on_trading_live_enabled(monkeypatch):
    """TRADING_LIVE_ENABLED is gone; even if some stale config still sets an
    attribute by that name, /trading/start must not treat it specially.

    settings is a pydantic BaseSettings instance -- plain monkeypatch.setattr
    (even with raising=False) refuses to set a field the model no longer
    declares, which is itself half the proof the flag is gone. object.__setattr__
    bypasses pydantic's own __setattr__ to simulate a stray leftover value
    (e.g. an old env var) actually landing on the instance."""
    monkeypatch.setattr(trading, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(trading, "YFinanceProvider", _ForeverQuoteProvider)
    monkeypatch.setattr(trading, "db", _FakeDb)
    _no_active_broker_session(monkeypatch)
    object.__setattr__(trading.settings, "TRADING_LIVE_ENABLED", True)
    try:
        for name in ("technical_breakout", "mean_reversion", "macd_crossover"):
            asyncio.run(_seed_passing_backtest(name))

        with TestClient(_start_app()) as test_client:
            resp = test_client.post("/api/v1/trading/start", json={
                "mode": "LONGTERM", "universe": ["RELIANCE"], "poll_interval_seconds": 0.01,
            })
            assert resp.status_code != 501
            run_id = resp.json()["run_id"]

            stop_resp = test_client.post("/api/v1/trading/stop", json={"run_id": run_id})
            assert stop_resp.json()["stopped"] is True
    finally:
        object.__delattr__(trading.settings, "TRADING_LIVE_ENABLED")


class _LiveAdapter:
    """Stands in for an ACTIVE broker adapter with an open position to
    reconcile -- state()/get_positions() are all /trading/start touches on
    the adapter directly (order placement goes through BrokerExecutionClient,
    not exercised by this route test)."""

    def __init__(self, state, positions=None):
        self._state = state
        self._positions = positions or {}

    async def state(self):
        return self._state

    async def get_positions(self):
        return self._positions


def _fresh_fake_db():
    """A per-test AsyncMongoMockClient, distinct from the module-level
    _FakeDb, so PrefsStore writes here can't leak live_strategies into
    other tests that reuse _FakeDb.db."""
    return type("_Db", (), {"db": AsyncMongoMockClient()["test_db"], "redis": None})()


async def _seed_gate_and_prefs(fake_db, live_strategies):
    from backend.components.shared.models import BacktestResult
    from backend.prefs import PrefsStore
    from backend.risk.backtest_gate import BacktestGateStore

    for name in ("technical_breakout", "mean_reversion", "macd_crossover"):
        await BacktestGateStore(fake_db.db).record(name, BacktestResult(
            symbol="RELIANCE", start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
            total_trades=40, win_rate=0.55, profit_factor=1.5, total_pnl=50_000.0,
            max_drawdown=0.10, sharpe_ratio=1.2, trades=[],
        ))
    await PrefsStore(fake_db.db).update(_USER.id, {"live_strategies": live_strategies})


def test_start_routes_a_toggled_live_strategy_and_reconciles_positions(monkeypatch):
    """All three conditions hold (toggled live, broker ACTIVE, backtest-gate
    eligible) -- the strategy must get a live BrokerExecutionClient and the
    broker's open position must land in the fresh Portfolio.

    Calls start_trading directly (not through TestClient/HTTP) so the whole
    scenario runs on one asyncio event loop we control -- start_background_run
    schedules run() as a task, and a no-await stub for it needs a couple of
    `sleep(0)` turns on that *same* loop to actually execute before we assert
    on what it was called with."""
    from backend.brokers.protocol import BrokerSessionState
    from backend.core.models import Position

    fake_db = _fresh_fake_db()
    monkeypatch.setattr(trading, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(trading, "YFinanceProvider", _ForeverQuoteProvider)
    monkeypatch.setattr(trading, "db", fake_db)

    broker_position = Position(symbol="RELIANCE", quantity=5.0, avg_price=2400.0)
    monkeypatch.setattr(
        trading, "get_active_broker_adapter",
        AsyncMock(return_value=_LiveAdapter(BrokerSessionState.ACTIVE, {"RELIANCE": broker_position})),
    )

    seen = {}

    async def _spying_run(**kwargs):
        seen["portfolio"] = kwargs["portfolio"]
        seen["execution"] = kwargs["execution"]

    monkeypatch.setattr(trading, "run", _spying_run)

    async def _scenario():
        await _seed_gate_and_prefs(fake_db, ["technical_breakout"])
        req = trading.StartRequest(mode="LONGTERM", universe=["RELIANCE"], poll_interval_seconds=0.01)
        await trading.start_trading(req, user=_USER, runs=RunStore(fake_db.db))
        for _ in range(5):
            await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert seen["portfolio"].positions["RELIANCE"].quantity == 5.0
    assert isinstance(seen["execution"], trading.RoutingExecutionClient)
    assert "technical_breakout" in seen["execution"]._live_by_strategy


class _NoopStrategy:
    """Minimal real Strategy -- a proper StrategySpec (owner_by_symbol
    scoping reads .spec.name/.spec.universe) with no-op lifecycle hooks,
    since start_trading itself never calls on_start/on_bar (run() is
    monkeypatched to a spy in these tests)."""

    def __init__(self, name: str, universe: list[str]):
        from backend.engine.protocols import StrategySpec

        self.spec = StrategySpec(name=name, mode="LONGTERM", timeframe="1d", warmup_bars=0, universe=universe)

    def on_start(self, ctx) -> None: ...
    def on_bar(self, ctx, bar) -> None: ...
    def on_fill(self, ctx, fill) -> None: ...


def test_start_reconciliation_only_merges_symbols_owned_by_live_strategies(monkeypatch):
    """A paper-only strategy's symbol (TCS, owned only by a strategy never
    toggled live) must not be seeded from the broker's position book, even
    though the broker holds a real position in it -- only RELIANCE (owned by
    the live-toggled strategy) should land in the fresh Portfolio."""
    from backend.brokers.protocol import BrokerSessionState
    from backend.core.models import Position

    fake_db = _fresh_fake_db()
    monkeypatch.setattr(trading, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(trading, "YFinanceProvider", _ForeverQuoteProvider)
    monkeypatch.setattr(trading, "db", fake_db)
    monkeypatch.setattr(
        trading, "build_default_strategies",
        lambda **kwargs: [
            _NoopStrategy("technical_breakout", ["RELIANCE"]),
            _NoopStrategy("mean_reversion", ["TCS"]),
        ],
    )

    broker_positions = {
        "RELIANCE": Position(symbol="RELIANCE", quantity=5.0, avg_price=2400.0),
        "TCS": Position(symbol="TCS", quantity=3.0, avg_price=3500.0),  # e.g. a manual trade
    }
    monkeypatch.setattr(
        trading, "get_active_broker_adapter",
        AsyncMock(return_value=_LiveAdapter(BrokerSessionState.ACTIVE, broker_positions)),
    )

    seen = {}

    async def _spying_run(**kwargs):
        seen["portfolio"] = kwargs["portfolio"]

    monkeypatch.setattr(trading, "run", _spying_run)

    async def _scenario():
        # Only technical_breakout (RELIANCE) is toggled live; mean_reversion
        # (TCS) stays paper-only.
        await _seed_gate_and_prefs(fake_db, ["technical_breakout"])
        req = trading.StartRequest(mode="LONGTERM", universe=["RELIANCE", "TCS"], poll_interval_seconds=0.01)
        await trading.start_trading(req, user=_USER, runs=RunStore(fake_db.db))
        for _ in range(5):
            await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert seen["portfolio"].positions["RELIANCE"].quantity == 5.0
    assert "TCS" not in seen["portfolio"].positions


def test_start_falls_back_to_paper_when_broker_session_is_not_active(monkeypatch):
    """Toggled live + backtest-gate eligible, but no ACTIVE broker session --
    default-to-paper wins; no live_by_strategy entries, plain paper execution."""
    fake_db = _fresh_fake_db()
    monkeypatch.setattr(trading, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(trading, "YFinanceProvider", _ForeverQuoteProvider)
    monkeypatch.setattr(trading, "db", fake_db)
    monkeypatch.setattr(trading, "get_active_broker_adapter", AsyncMock(return_value=None))

    seen = {}

    async def _spying_run(**kwargs):
        seen["execution"] = kwargs["execution"]

    monkeypatch.setattr(trading, "run", _spying_run)

    async def _scenario():
        await _seed_gate_and_prefs(fake_db, ["technical_breakout"])
        req = trading.StartRequest(mode="LONGTERM", universe=["RELIANCE"], poll_interval_seconds=0.01)
        await trading.start_trading(req, user=_USER, runs=RunStore(fake_db.db))
        for _ in range(5):
            await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert isinstance(seen["execution"], trading.SimulatedExecutionClient)
