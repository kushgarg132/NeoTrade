from datetime import datetime, timezone

from backend.core.models import Intent, Position, Side
from backend.engine.portfolio import Portfolio
from backend.engine.runner import size_intents
from backend.plan.gate import PlanGate, versions_source
from backend.tests.test_size_intents import _FakeCtx, _FakeStrategy, _no_sentiment_redis

NOW = datetime(2026, 10, 6, 4, 30, tzinfo=timezone.utc)


def _plan(**kw):
    return {"skip_day": False, "risk_multiplier": 1.0, "max_positions": 10,
            "allow": [{"symbol": "TCS", "strategies": ["orb_breakout"], "catalyst": None}], **kw}


async def _gate(plan):
    async def source(now):
        return plan
    gate = PlanGate(source)
    await gate.refresh(NOW)
    return gate


async def test_no_plan_allows_everything():
    gate = await _gate(None)
    assert gate.blocks("orb_breakout", "INFY", False, 99) is None and gate.multiplier == 1.0


async def test_blocks_pairs_outside_allow_and_skip_day():
    gate = await _gate(_plan())
    assert gate.blocks("orb_breakout", "TCS", False, 0) is None
    assert gate.blocks("vwap_reversion", "TCS", False, 0) == "plan: not in today's plan"
    assert gate.blocks("orb_breakout", "INFY", False, 0) == "plan: not in today's plan"
    assert (await _gate(_plan(skip_day=True))).blocks("orb_breakout", "TCS", False, 0) == "plan: skip day"


async def test_max_positions_counts_new_symbols_only():
    gate = await _gate(_plan(max_positions=1))
    assert gate.blocks("orb_breakout", "TCS", True, 1) is None
    assert gate.blocks("orb_breakout", "TCS", False, 1) == "plan: max positions"


async def test_refresh_reads_the_source_once_per_bar_time():
    calls = []

    async def source(now):
        calls.append(now)
        return None
    gate = PlanGate(source)
    await gate.refresh(NOW)
    await gate.refresh(NOW)
    assert calls == [NOW]


async def test_versions_source_follows_time():
    v1 = {"version": 1, "at": datetime(2026, 10, 6, 3, 30, tzinfo=timezone.utc)}   # 09:00 IST
    v2 = {"version": 2, "at": datetime(2026, 10, 6, 5, 30, tzinfo=timezone.utc)}   # 11:00 IST
    source = versions_source([v1, v2])
    assert (await source(datetime(2026, 10, 6, 4, 30, tzinfo=timezone.utc)))["version"] == 1
    assert (await source(datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc)))["version"] == 2
    assert await source(datetime(2026, 10, 6, 2, 30, tzinfo=timezone.utc)) is None


async def test_size_intents_never_blocks_a_closing_intent_and_scales_risk():
    orb = _FakeStrategy("INTRADAY", "orb_breakout")
    held = Portfolio()
    held.positions["TCS"] = Position(symbol="TCS", quantity=10.0, avg_price=100.0)
    closing = Intent(symbol="TCS", side=Side.SELL, strength=0.9, reason_codes=["x"], stop_hint=110.0,
                     strategy="orb_breakout")
    nothing = await _gate(_plan(allow=[]))
    orders = await size_intents([closing], held, _FakeCtx({"TCS": 100.0}), {"TCS": orb}, _no_sentiment_redis(),
                                account_size=1_000_000.0, max_exposure=1_000_000.0, plan=nothing)
    assert len(orders) == 1

    opening = Intent(symbol="INFY", side=Side.BUY, strength=0.9, reason_codes=["x"], stop_hint=95.0,
                     strategy="orb_breakout")

    async def qty(plan):
        orders = await size_intents([opening], Portfolio(), _FakeCtx({"INFY": 100.0}), {"INFY": orb},
                                    _no_sentiment_redis(), account_size=1_000_000.0, max_exposure=10_000_000.0,
                                    plan=plan)
        return orders[0].quantity if orders else 0
    half = await _gate(_plan(risk_multiplier=0.5, allow=[{"symbol": "INFY", "strategies": ["orb_breakout"]}]))
    full = await qty(None)
    assert full > 0 and abs(await qty(half) - full / 2) <= 1
    assert await qty(nothing) == 0
