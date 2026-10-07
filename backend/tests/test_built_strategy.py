import copy
import logging
import random
import time as clock
from datetime import date, datetime, timedelta

import pytest

from backend.core.models import Bar, Fill, Side
from backend.engine.session import IST
from backend.strategies.blocks.regime import regime_by_day
from backend.strategies.built import BlockStrategy, load_ok, set_active
from backend.strategies.registry import build_default_strategies

EXAMPLE = {
    "setup": {"gap": {"direction": "down", "min_pct": 1.0}},
    "filters": {"price_vs_vwap": {"side": "above"}, "volume_confirm": {"multiple": 2.0},
                "time_window": {"start": "09:30", "end": "14:45"}},
    "side": "long", "stop": {"atr_multiple": 1.0}, "target": {"r_multiple": 2.0},
}


@pytest.fixture(autouse=True)
def _reset_active():
    set_active([])
    yield
    set_active([])


class Ctx:
    def __init__(self):
        self.intents, self.pos = [], {}

    def position(self, symbol):
        return self.pos.get(symbol)

    def submit(self, intent):
        self.intents.append(intent)


def bar(day, i, c, v=1000, token=1, h=0.2):
    ts = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST) + timedelta(minutes=5 * i)
    return Bar(instrument_token=token, timeframe="5m", timestamp=ts, open=c, high=c + h, low=c - h, close=c, volume=v)


def dip_day(day, start, n=24):
    """Opens at `start`, dips 0.05 a bar for `n` bars, then reclaims VWAP on 2.2x volume at bar `n`
    (11:15 for n=24, once ATR and the 20-bar volume average have warmed up on today's bars)."""
    return [bar(day, i, start - 0.05 * i) for i in range(n)] + [bar(day, n, start + 1.0, v=2200)]


TODAY = date(2026, 10, 6)
ENTRY = 75 + 24  # index of the entry bar in crafted_day()


def crafted_day():
    """Flat prior day at 100, then gap -1.5%, a steady dip, and a VWAP reclaim at 11:15."""
    prior = [bar(date(2026, 10, 5), i, 100.0) for i in range(75)]
    return prior + dip_day(TODAY, 98.5) + [bar(TODAY, 25 + i, 99.5) for i in range(4)]


def run(strat, bars, ctx=None):
    ctx = ctx or Ctx()
    for b in bars:
        strat.on_bar(ctx, b)
    return ctx


def test_gap_down_vwap_reclaim_fires_once_with_reason_codes():
    strat = BlockStrategy("gdvr", EXAMPLE, ["X"], {1: "X"})
    ctx = run(strat, crafted_day())
    assert len(ctx.intents) == 1
    i = ctx.intents[0]
    assert i.side == Side.BUY
    assert i.reason_codes == ["built:gdvr", "gap", "price_vs_vwap", "volume_confirm", "time_window"]
    entry_atr = _atr_at(crafted_day()[:ENTRY + 1])  # ATR as of the 11:15 entry bar
    assert i.stop_hint == pytest.approx(99.5 - 1.0 * entry_atr)
    assert i.target_hint == pytest.approx(99.5 + 2 * (99.5 - i.stop_hint))


def _atr_at(bars):
    trs = []
    for prev, b in zip(bars, bars[1:]):
        trs.append(max(b.high - b.low, abs(b.high - prev.close), abs(b.low - prev.close)))
    return sum(trs[-14:]) / 14


def test_grid_is_one_step_either_side_and_clamped():
    spec = copy.deepcopy(EXAMPLE)
    spec["target"] = {"r_multiple": 1.0}
    strat = BlockStrategy("g", spec, ["X"], {1: "X"})
    assert strat.GRID["target.target.r_multiple"] == [1.0, 1.25]
    assert strat.GRID["setup.gap.min_pct"] == [0.75, 1.0, 1.25]
    assert strat.PARAMS["stop.stop.atr_multiple"] == 1.0


def test_params_override_spec_numbers():
    strat = BlockStrategy("p", EXAMPLE, ["X"], {1: "X"}, params={"target.target.r_multiple": 3.0, "bogus": 1})
    assert strat.p["target.target.r_multiple"] == 3.0
    ctx = run(strat, crafted_day())
    i = ctx.intents[0]
    assert i.target_hint == pytest.approx(99.5 + 3 * (99.5 - i.stop_hint))


def test_card_is_built_per_instance():
    spec = copy.deepcopy(EXAMPLE)
    spec["filters"]["regime_is"] = {"regimes": ["risk_on"]}
    card = BlockStrategy("c", spec, ["X"], {}, thesis="Gaps bounce.").CARD
    assert (card.style, card.regimes, card.needs, card.best_when, card.typical_hold_minutes) == (
        "momentum", ["risk_on"], ["gap"], "Gaps bounce.", 120)
    orb = {**EXAMPLE, "setup": {"orb_break": {"range_minutes": 15}}}
    other = BlockStrategy("o", orb, ["X"], {})
    assert (other.CARD.style, other.CARD.needs, other.CARD.typical_hold_minutes) == ("breakout", ["range_day"], 120)
    assert other.CARD.regimes == ["risk_on", "neutral", "risk_off"]


def test_load_ok():
    assert load_ok(EXAMPLE)
    assert not load_ok({**EXAMPLE, "setup": {"gone": {}}})
    assert not load_ok({**EXAMPLE, "side": "flat"})
    assert not load_ok({k: v for k, v in EXAMPLE.items() if k != "target"})
    assert not load_ok({**EXAMPLE, "stop": {"bogus": 1}})
    assert not load_ok({**EXAMPLE, "time_stop": {"minutes": 30}})  # dropped from the vocabulary (R16)
    assert load_ok({**EXAMPLE, "stop": {"setup_bar": True}})


def test_registry_adds_active_specs_and_skips_a_spec_that_no_longer_validates(caplog):
    set_active([{"slug": "ok", "spec": EXAMPLE}, {"slug": "old", "spec": {**EXAMPLE, "setup": {"gone": {}}}}])
    with caplog.at_level(logging.WARNING):
        names = [s.spec.name for s in build_default_strategies(universe=["X"])]
    assert "built:ok" in names and "built:old" not in names
    assert "old" in caplog.text
    set_active([])
    assert not any(n.startswith("built:") for n in (s.spec.name for s in build_default_strategies(universe=["X"])))


def test_regime_by_day_and_sector_rs():
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(201)]
    rising = regime_by_day([(d, 100.0 + i) for i, d in enumerate(days)])
    assert rising(days[-1] + timedelta(days=1)) == "risk_on"
    assert regime_by_day([(d, 100.0 - i * 0.1) for i, d in enumerate(days)])(days[-1] + timedelta(days=1)) == "risk_off"
    assert regime_by_day([(d, 100.0) for d in days[:199]])(days[-1]) is None

    syms = ["B1", "B2", "B3", "I1", "I2", "I3"]
    sector_of = {s: "BANK" if s[0] == "B" else "IT" for s in syms}
    spec = {**EXAMPLE, "filters": {"sector_rs": {"min": 0.5}}}
    strat = BlockStrategy("s", spec, syms, {n: s for n, s in enumerate(syms)}, sector_of=sector_of)
    day = date(2026, 10, 6)
    for n, s in enumerate(syms):
        strat.on_bar(Ctx(), bar(day, 0, 100.0, token=n))
        strat.on_bar(Ctx(), bar(day, 1, 102.0 if s[0] == "B" else 100.0, token=n))
    assert strat._sector_rs("B1", strat._states["B1"]) == pytest.approx(1.0)
    assert strat._sector_rs("I1", strat._states["I1"]) == pytest.approx(-1.0)


def test_throughput_at_least_1000_bars_per_second():
    spec = {**EXAMPLE, "setup": {"vwap_cross": {"mode": "reclaim"}},
            "filters": {**EXAMPLE["filters"], "atr_pct": {"min": 0.3, "max": 6.0}}}
    strat = BlockStrategy("t", spec, [f"S{k}" for k in range(10)], {k: f"S{k}" for k in range(10)})
    rng, price, ctx = random.Random(1), [100.0] * 10, Ctx()
    bars = []
    for n in range(5000):
        day = date(2026, 1, 1) + timedelta(days=n // 75)
        for k in range(10):
            price[k] *= 1 + rng.uniform(-0.004, 0.004)
            bars.append(bar(day, n % 75, price[k], v=rng.randint(500, 3000), token=k))
    start = clock.perf_counter()
    for b in bars:
        strat.on_bar(ctx, b)
    assert clock.perf_counter() - start < 50


def test_enters_at_most_once_per_symbol_per_day():
    strat = BlockStrategy("d", EXAMPLE, ["X"], {1: "X"})
    bars = crafted_day()
    ctx = run(strat, bars[:ENTRY + 1])
    assert len(ctx.intents) == 1
    # stop-out: a fill leaves the book flat, then the setup and filters pass again the same day
    strat.on_fill(ctx, Fill(order_id="2", symbol="X", side=Side.SELL, quantity=10, price=98.0,
                            timestamp=bars[ENTRY].timestamp))
    run(strat, [bar(TODAY, 25, 99.6, v=2200)], ctx)
    assert len(ctx.intents) == 1
    nxt = date(2026, 10, 7)
    run(strat, dip_day(nxt, 98.0), ctx)
    assert len(ctx.intents) == 2


@pytest.mark.parametrize("regime,count", [("risk_off", 0), ("risk_on", 1)])
def test_regime_filter_gates_entry_through_on_bar(regime, count):
    spec = {**EXAMPLE, "filters": {**EXAMPLE["filters"], "regime_is": {"regimes": ["risk_on"]}}}
    strat = BlockStrategy("r", spec, ["X"], {1: "X"}, regime_of=lambda day: regime)
    assert len(run(strat, crafted_day()).intents) == count


def test_each_session_starts_fresh_no_indicator_carry_over():
    strat = BlockStrategy("f", EXAMPLE, ["X"], {1: "X"})
    run(strat, [bar(date(2026, 10, 5), i, 100.0) for i in range(30)])
    assert strat._states["X"].atr is not None
    for i in range(14):
        run(strat, [bar(TODAY, i, 99.0)])
        assert (strat._states["X"].atr is None) == (i < 13), i
    assert strat._states["X"].prev_close == 100.0


def _key(intents):
    return [(i.symbol, i.side, i.reason_codes, i.stop_hint, i.target_hint) for i in intents]


def test_live_feed_with_prev_closes_matches_backtest_with_yesterdays_bars():
    today_only = dip_day(TODAY, 98.5) + [bar(TODAY, 25 + i, 99.5) for i in range(4)]
    live = BlockStrategy("l", EXAMPLE, ["X"], {1: "X"}, prev_closes={TODAY.isoformat(): {"X": 100.0}})
    live_intents = run(live, today_only).intents
    assert len(live_intents) == 1 and live_intents[0].reason_codes[1] == "gap"  # the gap fires live
    backtest = BlockStrategy("l", EXAMPLE, ["X"], {1: "X"})
    assert _key(run(backtest, crafted_day()).intents) == _key(live_intents)
    # Without either, there is no previous close and the gap cannot fire.
    assert run(BlockStrategy("l", EXAMPLE, ["X"], {1: "X"}), today_only).intents == []


def test_registry_skips_a_spec_that_passes_load_ok_but_fails_to_build(caplog):
    bad = {**EXAMPLE, "setup": {"orb_break": {"range_minutes": "x"}}}
    assert load_ok(bad)
    set_active([{"slug": "bad", "spec": bad}, {"slug": "ok", "spec": EXAMPLE}])
    with caplog.at_level(logging.WARNING):
        names = [s.spec.name for s in build_default_strategies(universe=["X"])]
    assert "built:ok" in names and "built:bad" not in names
    assert "bad" in caplog.text
