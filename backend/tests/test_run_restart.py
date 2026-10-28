"""A restart must not forget open intraday positions, and one worker's
startup must not stop another worker's live runs. On 2026-10-05 six of seven
intraday runs were orphaned by deploys; each started from an empty portfolio,
16 trades were left open, and CONCOR was bought across five runs (66 shares)
against a Rs 5,000 per-stock cap."""

from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine.adopt import adopt_intraday, booked_today, close_stale
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST
from backend.runs import BOOT_ID, RunStore

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=IST)


def _trade(symbol, side, qty, price, entry, strategy="vwap_reversion", mode="INTRADAY", status="OPEN"):
    return {"id": f"t-{symbol}", "user_id": "alice", "symbol": symbol, "side": side, "quantity": qty,
            "entry_price": price, "entry_at": entry, "mode": mode, "status": status, "strategy": strategy,
            "venue": "paper"}


@pytest.fixture
def db():
    return AsyncMongoMockClient()["test_db"]


async def test_todays_open_intraday_trades_are_adopted_with_their_owner(db):
    await db["paper_trades"].insert_many([
        _trade("CONCOR", "BUY", 11, 436.85, datetime(2026, 10, 5, 6, 20, tzinfo=timezone.utc)),
        _trade("ASTRAL", "SELL", 3, 1351.2, datetime(2026, 10, 5, 6, 20, tzinfo=timezone.utc), strategy="orb_breakout"),
        _trade("ITC", "BUY", 5, 400.0, datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc), mode="LONGTERM"),
        _trade("OLD", "BUY", 7, 100.0, datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)),
    ])
    positions, holders, stale, _ = await adopt_intraday(db, "alice", NOW)
    assert {s: (p.quantity, p.avg_price) for s, p in positions.items()} == {"CONCOR": (11, 436.85), "ASTRAL": (-3, 1351.2)}
    assert holders == {"CONCOR": "vwap_reversion", "ASTRAL": "orb_breakout"}
    assert [t["symbol"] for t in stale] == ["OLD"]


async def test_stale_intraday_trades_are_closed_at_their_mark(db):
    ledger = LedgerStore(db, user_id="alice")
    from backend.suggestions.service import execute_suggestion
    await execute_suggestion({"symbol": "OLD", "side": "BUY", "quantity": 7, "mode": "INTRADAY"}, ledger, 100.0)
    stale = await db["paper_trades"].find({"user_id": "alice", "status": "OPEN"}).to_list(10)

    async def mark(symbol):
        return 104.0

    closed = await close_stale(ledger, stale, mark, NOW)
    assert closed == 1
    trade = await db["paper_trades"].find_one({"user_id": "alice", "symbol": "OLD"})
    assert trade["status"] == "CLOSED" and trade["exit_price"] == 103.9  # the 104 mark less 10 bps slippage


async def test_a_stale_trade_without_a_price_stays_for_the_next_pass(db):
    ledger = LedgerStore(db, user_id="alice")

    async def no_price(symbol):
        raise RuntimeError("no quote")

    stale = [_trade("OLD", "BUY", 7, 100.0, datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc))]
    assert await close_stale(ledger, stale, no_price, NOW) == 0


class _Redis:
    def __init__(self, alive):
        self.alive = set(alive)

    async def exists(self, key):
        return 1 if key in self.alive else 0


async def test_only_runs_whose_worker_is_gone_are_orphaned(db):
    runs = RunStore(db)
    await runs.create("mine", "alice", "INTRADAY", ["X"], {})          # this worker: alive
    await db["trading_runs"].insert_one({"run_id": "other", "status": "RUNNING", "boot_id": "worker-b"})
    await db["trading_runs"].insert_one({"run_id": "dead", "status": "RUNNING", "boot_id": "worker-gone"})
    await db["trading_runs"].insert_one({"run_id": "legacy", "status": "RUNNING"})  # before boot ids
    assert (await runs.get("mine"))["boot_id"] == BOOT_ID

    closed = await runs.close_orphaned(_Redis({f"worker:alive:{BOOT_ID}", "worker:alive:worker-b"}))

    assert closed == 2
    status = {r["run_id"]: r["status"] async for r in db["trading_runs"].find({})}
    assert status == {"mine": "RUNNING", "other": "RUNNING", "dead": "STOPPED", "legacy": "STOPPED"}


async def test_several_open_trades_on_one_stock_are_netted(db):
    """Runs that started empty opened a fresh trade for a stock already held,
    so one stock can carry several open intraday trades: adoption nets them."""
    t = datetime(2026, 10, 5, 6, 20, tzinfo=timezone.utc)
    await db["paper_trades"].insert_many([
        {**_trade("CONCOR", "BUY", 22, 440.0, t), "id": "c1"},
        {**_trade("CONCOR", "BUY", 11, 435.5, t), "id": "c2"},
        {**_trade("ASTRAL", "SELL", 3, 1351.2, t), "id": "a1"},
        {**_trade("ASTRAL", "BUY", 3, 1357.0, t), "id": "a2"},
    ])
    positions, holders, _, _ = await adopt_intraday(db, "alice", NOW)
    assert positions["CONCOR"].quantity == 33
    assert round(positions["CONCOR"].avg_price, 2) == round((22 * 440.0 + 11 * 435.5) / 33, 2)
    assert "ASTRAL" not in positions and "ASTRAL" not in holders  # nets to flat


async def test_adopted_trade_keeps_its_pnl_across_a_restart(db):
    """A second trade on a stock in one run carries `realized_base` (what the
    symbol had already realized); an adopted position starting at 0 made the
    trade's close book P&L minus that base."""
    from backend.core.models import Fill
    from backend.engine.portfolio import Portfolio

    t = datetime(2026, 10, 5, 6, 20, tzinfo=timezone.utc)
    await db["paper_trades"].insert_many([
        {**_trade("ITC", "BUY", 5, 90.0, t, status="CLOSED"), "id": "first", "realized_pnl": 500.0, "costs": 0.0,
         "exit_at": t},
        {**_trade("ITC", "BUY", 10, 100.0, t), "id": "second", "realized_base": 500.0, "realized_pnl": 20.0},
    ])
    positions, _, _, _ = await adopt_intraday(db, "alice", NOW)
    assert positions["ITC"].realized_pnl == 520.0

    portfolio = Portfolio()
    portfolio.positions.update(positions)
    ledger = LedgerStore(db, user_id="alice")
    # The kill switch sees 500 once, not the closed trade plus the seeded base.
    assert await booked_today(ledger, NOW, positions) + portfolio.equity({"ITC": 100.0}) == 500.0

    fill = Fill(order_id="x", symbol="ITC", side="SELL", quantity=10, price=110.0, timestamp=NOW)
    portfolio.apply(fill)
    await ledger.on_fill(fill, 10, portfolio.positions["ITC"])
    trade = await db["paper_trades"].find_one({"id": "second"})
    assert trade["status"] == "CLOSED" and trade["realized_pnl"] == 120.0  # 20 earlier + 100 now


async def test_only_todays_own_intraday_closes_count_toward_the_loss_limit(db):
    """A long-term exit, yesterday's position closed by close_stale and the
    autopilot's trades are not today's intraday losses."""
    today, yesterday = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc), datetime(2026, 10, 3, 5, 0, tzinfo=timezone.utc)

    def closed(id_, pnl, entry, **extra):
        return {**_trade(id_, "BUY", 1, 100.0, entry, status="CLOSED"), "id": id_, "realized_pnl": pnl,
                "costs": 0.0, "exit_at": today, **extra}

    await db["paper_trades"].insert_many([
        closed("A", -300.0, today),
        closed("B", -5_000.0, today, mode="LONGTERM"),
        closed("C", -4_000.0, yesterday),  # close_stale
        closed("D", -2_000.0, today, via="autopilot:x"),
    ])
    assert await booked_today(LedgerStore(db, user_id="alice"), NOW, {}) == -300.0


async def test_adopted_position_keeps_its_stop_after_a_restart(db):
    from backend.engine.runner import run  # noqa: F401  (levels seed shape is run()'s)

    ctx = {"stop": 95.0, "target": 120.0, "max_hold_days": None, "trail_atr": None}
    t = datetime(2026, 10, 5, 6, 20, tzinfo=timezone.utc)
    await db["paper_trades"].insert_many([
        {**_trade("AAA", "BUY", 10, 100.0, t), "context": ctx},
        {**_trade("BBB", "BUY", 10, 100.0, t), "context": {}},  # no stop: nothing to seed
    ])
    _, _, _, levels = await adopt_intraday(db, "alice", NOW)
    assert set(levels) == {"AAA"}
    assert levels["AAA"]["stop"] == 95.0 and levels["AAA"]["target"] == 120.0
    assert levels["AAA"]["fresh"] is False and levels["AAA"]["product"] == "MIS"


async def test_restarted_run_exits_an_adopted_long_at_its_stop(db):
    from datetime import timedelta
    from backend.core.clock import SimClock
    from backend.core.models import Bar
    from backend.engine.execution.simulated import SimulatedExecutionClient
    from backend.engine.portfolio import Portfolio
    from backend.engine.protocols import StrategySpec
    from backend.engine.runner import run

    class _Idle:
        spec = StrategySpec(name="vwap_reversion", mode="INTRADAY", timeframe="5m", warmup_bars=0, universe=["ITC"])

        def on_start(self, ctx): ...
        def on_fill(self, ctx, fill): ...
        def on_bar(self, ctx, bar): ...

    t = datetime(2026, 10, 5, 6, 20, tzinfo=timezone.utc)
    await db["paper_trades"].insert_one({**_trade("ITC", "BUY", 10, 100.0, t), "context": {"stop": 95.0}})
    positions, holders, _, levels = await adopt_intraday(db, "alice", NOW)
    portfolio = Portfolio()
    portfolio.positions.update(positions)

    class _Feed:
        async def __aiter__(self):
            for i, (o, h, l, c) in enumerate([(100, 101, 99, 100), (100, 100, 94, 96)]):
                yield Bar(instrument_token=1, timeframe="5m", timestamp=NOW + timedelta(minutes=5 * i),
                          open=o, high=h, low=l, close=c, volume=1000.0)

    await run(strategies=[_Idle()], feed=_Feed(), execution=SimulatedExecutionClient(fill_on_next_open=True),
              portfolio=portfolio, clock=SimClock(), symbol_for_token={1: "ITC"}, account_size=25_000.0,
              max_exposure=15_000.0, per_trade_cap=5_000.0, holders=holders, levels=levels)
    assert "ITC" not in portfolio.positions or portfolio.positions["ITC"].quantity == 0


async def test_restarted_run_exits_an_adopted_option_when_its_underlying_hits_the_stop(db):
    """An adopted bought call used to get no option leg: no stop, no target, no
    15:15 square-off after a restart."""
    from datetime import timedelta
    from backend.core.clock import SimClock
    from backend.core.models import Bar
    from backend.engine.adopt import option_legs
    from backend.engine.execution.simulated import SimulatedExecutionClient
    from backend.engine.portfolio import Portfolio
    from backend.engine.protocols import StrategySpec
    from backend.engine.runner import run
    from backend.instruments.models import Instrument

    call = Instrument(exchange="NFO", tradingsymbol="RELIANCE26OCT2900CE", name="RELIANCE", instrument_token=9,
                      exchange_token=9, instrument_type="CE", segment="NFO-OPT", lot_size=250, tick_size=0.05,
                      expiry=datetime(2026, 10, 27), strike=2900.0)

    class _Master:
        async def get(self, exchange, symbol):
            return call if (exchange, symbol) == ("NFO", call.tradingsymbol) else None

    class _Idle:
        spec = StrategySpec(name="orb_options", mode="INTRADAY", timeframe="5m", warmup_bars=0, universe=["RELIANCE"])

        def on_start(self, ctx): ...
        def on_fill(self, ctx, fill): ...
        def on_bar(self, ctx, bar): ...

    t = datetime(2026, 10, 5, 6, 20, tzinfo=timezone.utc)
    await db["paper_trades"].insert_many([
        {**_trade(call.tradingsymbol, "BUY", 250, 12.0, t, strategy="orb_options"),
         "context": {"stop": 2850.0, "target": 2950.0}},
        {**_trade("ITC", "BUY", 10, 100.0, t), "context": {"stop": 95.0}},
    ])
    positions, holders, _, levels = await adopt_intraday(db, "alice", NOW)
    legs = await option_legs(_Master(), positions, holders, levels, NOW)
    assert set(legs) == {call.tradingsymbol} and set(levels) == {"ITC"}
    leg = legs[call.tradingsymbol]
    assert (leg["underlying"], leg["bullish"], leg["stop"], leg["target"]) == ("RELIANCE", True, 2850.0, 2950.0)

    portfolio = Portfolio()
    portfolio.positions.update(positions)

    class _Feed:
        async def __aiter__(self):
            for i, c in enumerate([2880.0, 2840.0, 2830.0]):
                yield Bar(instrument_token=1, timeframe="5m", timestamp=NOW + timedelta(minutes=5 * i),
                          open=c, high=c, low=c, close=c, volume=1000.0)

    await run(strategies=[_Idle()], feed=_Feed(), execution=SimulatedExecutionClient(fill_on_next_open=True),
              portfolio=portfolio, clock=SimClock(), symbol_for_token={1: "RELIANCE"}, account_size=25_000.0,
              max_exposure=15_000.0, per_trade_cap=5_000.0, holders=holders, levels=levels, option_legs=legs)
    assert portfolio.positions[call.tradingsymbol].quantity == 0
