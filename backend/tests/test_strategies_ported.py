"""Each ported strategy (backend/strategies/{longterm,intraday}/) fed a
synthetic bar sequence engineered to trigger its signal, through the
Strategy.on_bar interface directly -- no full engine run needed. Fixture
construction mirrors test_signal_integrity.py's _breakout_frame/_oversold_frame
approach, adapted to Bars instead of a DataFrame.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.core.clock import SimClock
from backend.core.models import Bar, Side
from backend.engine.context import SimpleStrategyContext
from backend.engine.portfolio import Portfolio
from backend.strategies.intraday.orb_breakout import ORBStrategy
from backend.strategies.intraday.rsi_momentum_scalp import RSIMomentumScalpStrategy
from backend.strategies.intraday.volume_surge import VolumeSurgeStrategy
from backend.strategies.intraday.vwap_reversion import VWAPReversionStrategy
from backend.strategies.longterm.analyst_verdict import AnalystVerdictStrategy
from backend.strategies.longterm.breakout import TechnicalBreakoutStrategy
from backend.strategies.longterm.cash_secured_put import CashSecuredPutStrategy
from backend.strategies.longterm.macd_crossover import MACDCrossoverStrategy
from backend.strategies.longterm.mean_reversion import MeanReversionStrategy
from backend.strategies.registry import build_default_strategies

SYMBOL = "TEST"
TOKEN = 111


def _bars(closes, opens=None, highs=None, lows=None, volumes=None, timeframe="1d",
          start=None, step=None) -> list[Bar]:
    n = len(closes)
    opens = opens or closes
    highs = highs or [c + 1 for c in closes]
    lows = lows or [c - 1 for c in closes]
    volumes = volumes if volumes is not None else [1000.0] * n
    start = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    step = step or (timedelta(days=1) if timeframe == "1d" else timedelta(minutes=5))
    return [
        Bar(
            instrument_token=TOKEN, timeframe=timeframe, timestamp=start + i * step,
            open=opens[i], high=highs[i], low=lows[i], close=closes[i], volume=volumes[i],
        )
        for i in range(n)
    ]


def _run(strategy, bars: list[Bar]):
    """Feeds every bar into a real SimpleStrategyContext (as the runner
    would), calling on_bar only for the final bar, and returns whatever
    Intents it emitted."""
    ctx = SimpleStrategyContext(SimClock(), Portfolio(), {TOKEN: SYMBOL})
    for bar in bars[:-1]:
        ctx.update(bar)
    ctx.update(bars[-1])
    strategy.on_bar(ctx, bars[-1])
    return ctx.drain_intents()


def _flat_bars(n: int, timeframe: str = "1d") -> list[Bar]:
    return _bars([100.0] * n, volumes=[1000.0] * n, timeframe=timeframe)


# ---------------------------------------------------------------------------
# TechnicalBreakoutStrategy
# ---------------------------------------------------------------------------

def _breakout_bars() -> list[Bar]:
    """A single symmetric hump (local max ~110 around index 24) followed by
    a decline back to ~90, then a final bar that breaks back above the hump
    with a volume spike -- 50 bars total, matching warmup_bars=50."""
    n = 50
    closes = []
    for i in range(n - 1):
        if i <= 24:
            closes.append(90.0 + i * (20.0 / 24.0))
        else:
            closes.append(110.0 - (i - 24) * (20.0 / 20.0))
    closes.append(115.0)  # final bar: breakout above the ~110 resistance
    volumes = [1000.0] * (n - 1) + [999_999.0]
    return _bars(closes, volumes=volumes)


def test_breakout_strategy_emits_buy_intent():
    strategy = TechnicalBreakoutStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _breakout_bars())

    assert len(intents) == 1
    intent = intents[0]
    assert intent.symbol == SYMBOL
    assert intent.side == Side.BUY
    assert 0.55 <= intent.strength <= 0.95  # graded, was a flat 0.8
    assert intent.reason_codes == ["breakout_above_resistance_with_volume"]
    assert intent.stop_hint is not None
    assert intent.target_hint is not None


def test_breakout_strategy_silent_on_flat_bars():
    strategy = TechnicalBreakoutStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _flat_bars(60))
    assert intents == []


# ---------------------------------------------------------------------------
# MeanReversionStrategy
# ---------------------------------------------------------------------------

def _oversold_bars() -> list[Bar]:
    """Quiet base then a sharp selloff, mirroring
    test_signal_integrity.py::_oversold_frame."""
    closes = [100.0] * 50 + [96.0, 92.0, 88.0, 84.0, 80.0]
    return _bars(closes)


def test_mean_reversion_strategy_emits_buy_intent():
    strategy = MeanReversionStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _oversold_bars())

    assert len(intents) == 1
    intent = intents[0]
    assert intent.symbol == SYMBOL
    assert intent.side == Side.BUY
    assert 0.5 <= intent.strength <= 0.9  # graded, was a flat 0.7
    assert intent.reason_codes == ["oversold_rsi_below_lower_band"]


def test_mean_reversion_strategy_silent_on_flat_bars():
    strategy = MeanReversionStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _flat_bars(60))
    assert intents == []


# ---------------------------------------------------------------------------
# CashSecuredPutStrategy
# ---------------------------------------------------------------------------

def test_cash_secured_put_fires_on_oversold_fo_eligible_symbol():
    # RELIANCE is in resolver.STRIKE_INTERVALS (F&O-eligible); SYMBOL (this
    # file's own test constant, "TEST") is not. This file's shared `_run()`
    # hardcodes its SimpleStrategyContext's symbol_for_token to
    # {TOKEN: SYMBOL}, so a different underlying needs its own context built
    # the same way `_run()` builds one, just keyed to "RELIANCE" instead.
    strategy = CashSecuredPutStrategy(["RELIANCE"], {TOKEN: "RELIANCE"})
    bars = _oversold_bars()
    ctx = SimpleStrategyContext(SimClock(), Portfolio(), {TOKEN: "RELIANCE"})
    for bar in bars[:-1]:
        ctx.update(bar)
    ctx.update(bars[-1])
    strategy.on_bar(ctx, bars[-1])
    intents = ctx.drain_intents()
    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.SELL
    assert intent.option_flavor == "CSP"
    assert intent.symbol == "RELIANCE"


def test_cash_secured_put_silent_for_non_fo_eligible_symbol():
    # SYMBOL ("TEST") is not in resolver.STRIKE_INTERVALS -- same oversold
    # bars, but is_fo_eligible gates it out before the RSI/Bollinger check
    # ever runs.
    strategy = CashSecuredPutStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _oversold_bars())
    assert intents == []


# ---------------------------------------------------------------------------
# MACDCrossoverStrategy
# ---------------------------------------------------------------------------

def _macd_bullish_crossover_bars() -> list[Bar]:
    """A steady decline (drives MACD histogram negative) followed by a sharp
    2-bar rally that flips the histogram positive exactly on the final bar
    (verified against the real MACD math, not guessed -- see report)."""
    decline = [140.0 - i * 2.0 for i in range(32)]  # 140 -> 78
    rally = [decline[-1] + i * 6.0 for i in range(1, 3)]  # two sharp up-bars
    closes = decline + rally
    return _bars(closes)


def test_macd_crossover_strategy_emits_bullish_buy_intent():
    strategy = MACDCrossoverStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _macd_bullish_crossover_bars())

    assert len(intents) == 1
    intent = intents[0]
    assert intent.symbol == SYMBOL
    assert intent.side == Side.BUY
    assert 0.5 <= intent.strength <= 0.9  # graded, was a flat 0.75
    assert intent.reason_codes == ["macd_bullish_crossover"]


def test_macd_crossover_strategy_emits_bearish_sell_intent():
    bullish_bars = _macd_bullish_crossover_bars()
    # Mirror image: rally then sharp selloff -> histogram flips positive-to-negative.
    closes = [200.0 - (b.close - 100.0) for b in bullish_bars]
    bars = _bars(closes)

    strategy = MACDCrossoverStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, bars)

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.SELL
    assert 0.5 <= intent.strength <= 0.9  # graded, was a flat 0.75
    assert intent.reason_codes == ["macd_bearish_crossover"]


def test_macd_crossover_strategy_silent_on_flat_bars():
    strategy = MACDCrossoverStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _flat_bars(40))
    assert intents == []


# ---------------------------------------------------------------------------
# VolumeSurgeStrategy
# ---------------------------------------------------------------------------

def _volume_surge_bars(bullish: bool) -> list[Bar]:
    n = 20
    closes = [100.0] * (n - 1)
    opens = [100.0] * (n - 1)
    if bullish:
        closes.append(103.0)
        opens.append(100.0)
    else:
        closes.append(97.0)
        opens.append(100.0)
    volumes = [1000.0] * (n - 1) + [10_000.0]
    return _bars(closes, opens=opens, volumes=volumes, timeframe="5m")


def test_volume_surge_strategy_emits_buy_intent_on_up_bar():
    strategy = VolumeSurgeStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _volume_surge_bars(bullish=True))

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.BUY
    assert intent.strength == 0.6
    assert intent.reason_codes == ["massive_buying_volume"]


def test_volume_surge_strategy_emits_sell_intent_on_down_bar():
    strategy = VolumeSurgeStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _volume_surge_bars(bullish=False))

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.SELL
    assert intent.strength == 0.6
    assert intent.reason_codes == ["massive_selling_volume"]


def test_volume_surge_strategy_silent_on_flat_bars():
    strategy = VolumeSurgeStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _flat_bars(25, timeframe="5m"))
    assert intents == []


# ---------------------------------------------------------------------------
# VWAPReversionStrategy
# ---------------------------------------------------------------------------

def _vwap_reversion_bars(bullish: bool) -> list[Bar]:
    """20 flat base bars (stable ~100 vwap) then a sharp move away from vwap,
    then a final bar ticking back toward it -- the reversion signal."""
    base = [100.0] * 20
    if bullish:
        move, tick = 95.0, 97.0  # drop 5%, then tick up (reverting toward vwap)
    else:
        move, tick = 105.0, 103.0  # spike 5%, then tick down
    closes = base + [move, tick]
    return _bars(closes, timeframe="5m")


def test_vwap_reversion_strategy_emits_buy_intent():
    strategy = VWAPReversionStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _vwap_reversion_bars(bullish=True))

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.BUY
    assert intent.reason_codes == ["vwap_reversion"]


def test_vwap_reversion_strategy_emits_sell_intent():
    strategy = VWAPReversionStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _vwap_reversion_bars(bullish=False))

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.SELL
    assert intent.reason_codes == ["vwap_reversion"]


def test_vwap_reversion_strategy_silent_on_flat_bars():
    strategy = VWAPReversionStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _flat_bars(25, timeframe="5m"))
    assert intents == []


# ---------------------------------------------------------------------------
# ORBStrategy
# ---------------------------------------------------------------------------

def _orb_bars(bullish: bool) -> list[Bar]:
    """3 opening-range bars (closes 100/101/99 -> or_high=102, or_low=98),
    10 flat filler bars (so atr_14's 14-bar window is populated by the final
    bar), then a final bar that clears the range on a volume spike."""
    range_closes = [100.0, 101.0, 99.0]
    filler = [100.0] * 10
    breakout_close = 105.0 if bullish else 95.0
    closes = range_closes + filler + [breakout_close]
    volumes = [1000.0] * 13 + [5000.0]
    return _bars(closes, volumes=volumes, timeframe="5m")


def test_orb_strategy_emits_buy_intent_on_upside_breakout():
    strategy = ORBStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _orb_bars(bullish=True))

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.BUY
    assert intent.reason_codes == ["orb_breakout"]


def test_orb_strategy_emits_sell_intent_on_downside_breakout():
    strategy = ORBStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _orb_bars(bullish=False))

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.SELL
    assert intent.reason_codes == ["orb_breakout"]


def test_orb_strategy_silent_on_flat_bars():
    strategy = ORBStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _flat_bars(25, timeframe="5m"))
    assert intents == []


# ---------------------------------------------------------------------------
# RSIMomentumScalpStrategy
# ---------------------------------------------------------------------------

def _rsi_momentum_bullish_bars() -> list[Bar]:
    """A gentle 18-bar decline (100 -> 91.5) followed by a sharp 2-bar rally
    that flips RSI(14) from 51.8 to 69.0, crossing the 60 bull threshold,
    with the final close (101.5) above ema_9 (95.6) -- verified against the
    real Indicators math, not guessed."""
    decline = [100.0 - i * 0.5 for i in range(18)]
    rally = [decline[-1] + i * 5.0 for i in range(1, 3)]
    return _bars(decline + rally, timeframe="5m")


def test_rsi_momentum_scalp_strategy_emits_buy_intent():
    strategy = RSIMomentumScalpStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _rsi_momentum_bullish_bars())

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.BUY
    assert intent.reason_codes == ["rsi_momentum_scalp"]


def test_rsi_momentum_scalp_strategy_emits_sell_intent():
    bullish_bars = _rsi_momentum_bullish_bars()
    # Mirror image: rally then sharp decline -> RSI flips 48.2 -> 31.0, crossing the 40 bear threshold.
    closes = [200.0 - b.close for b in bullish_bars]
    bars = _bars(closes, timeframe="5m")

    strategy = RSIMomentumScalpStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, bars)

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.SELL
    assert intent.reason_codes == ["rsi_momentum_scalp"]


def test_rsi_momentum_scalp_strategy_silent_on_flat_bars():
    strategy = RSIMomentumScalpStrategy([SYMBOL], {TOKEN: SYMBOL})
    intents = _run(strategy, _flat_bars(25, timeframe="5m"))
    assert intents == []


# ---------------------------------------------------------------------------
# registry.build_default_strategies
# ---------------------------------------------------------------------------

def test_build_default_strategies_returns_expected_twelve():
    strategies = build_default_strategies(universe=[SYMBOL])
    assert len(strategies) == 12

    by_mode_timeframe = sorted((s.spec.mode, s.spec.timeframe) for s in strategies)
    assert by_mode_timeframe == [("INTRADAY", "5m")] * 8 + [
        ("LONGTERM", "1d"),
        ("LONGTERM", "1d"),
        ("LONGTERM", "1d"),
        ("LONGTERM", "1d"),
    ]
    assert all(s.spec.universe == [SYMBOL] for s in strategies)


def test_build_default_strategies_omits_quality_momentum_without_universe():
    strategies = build_default_strategies(universe=[SYMBOL])
    assert all(s.spec.name != "quality_momentum" for s in strategies)


def test_build_default_strategies_includes_quality_momentum_when_provided():
    strategies = build_default_strategies(
        universe=[SYMBOL],
        quality_universe=[SYMBOL],
        quality_scores={SYMBOL: 0.6},
    )
    assert len(strategies) == 13

    quality_strategy = next(s for s in strategies if s.spec.name == "quality_momentum")
    assert quality_strategy.spec.mode == "LONGTERM"
    assert quality_strategy.spec.timeframe == "1d"
    assert quality_strategy.spec.universe == [SYMBOL]


# ---------------------------------------------------------------------------
# AnalystVerdictStrategy
# ---------------------------------------------------------------------------

def _bullish_verdict(**overrides) -> dict:
    verdict = {"sentiment_score": 0.6, "impact_score": 8, "label": "bullish", "top_reason": "Beat estimates by 12%"}
    verdict.update(overrides)
    return verdict


def test_analyst_verdict_strategy_fires_on_bullish_high_impact_verdict():
    strategy = AnalystVerdictStrategy([SYMBOL], {TOKEN: SYMBOL}, {SYMBOL: _bullish_verdict()})
    intents = _run(strategy, _flat_bars(1))

    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.BUY
    assert intent.reason_codes == ["analyst_bullish_verdict", "Beat estimates by 12%"]
    # RULE_FLOOR + AI_CAP * fraction = 0.45 + 0.30 * ((0.6 + 1) / 2) = 0.45 + 0.30 * 0.8 = 0.69
    assert intent.strength == pytest.approx(0.69)


def test_analyst_verdict_strategy_silent_below_impact_threshold():
    strategy = AnalystVerdictStrategy([SYMBOL], {TOKEN: SYMBOL}, {SYMBOL: _bullish_verdict(impact_score=3)})
    intents = _run(strategy, _flat_bars(1))
    assert intents == []


def test_analyst_verdict_strategy_silent_when_not_bullish():
    strategy = AnalystVerdictStrategy([SYMBOL], {TOKEN: SYMBOL}, {SYMBOL: _bullish_verdict(label="neutral")})
    intents = _run(strategy, _flat_bars(1))
    assert intents == []


def test_analyst_verdict_strategy_silent_for_symbol_with_no_verdict():
    strategy = AnalystVerdictStrategy([SYMBOL], {TOKEN: SYMBOL}, {})
    intents = _run(strategy, _flat_bars(1))
    assert intents == []


def test_analyst_verdict_strategy_clamps_out_of_range_sentiment_score():
    # A hallucinated LLM score outside [-1, 1] must not crash Intent construction.
    strategy = AnalystVerdictStrategy([SYMBOL], {TOKEN: SYMBOL}, {SYMBOL: _bullish_verdict(sentiment_score=1.4)})
    intents = _run(strategy, _flat_bars(1))
    assert len(intents) == 1
    # clamped fraction = 1.0 -> RULE_FLOOR + AI_CAP * 1.0 = 0.45 + 0.30 = 0.75
    assert intents[0].strength == pytest.approx(0.75)


def test_build_default_strategies_includes_analyst_verdict_when_provided():
    strategies = build_default_strategies(
        universe=[SYMBOL],
        analyst_verdicts={SYMBOL: _bullish_verdict()},
    )
    assert len(strategies) == 13

    verdict_strategy = next(s for s in strategies if s.spec.name == "analyst_verdict")
    assert verdict_strategy.spec.mode == "LONGTERM"
    assert verdict_strategy.spec.timeframe == "1d"
    assert verdict_strategy.spec.universe == [SYMBOL]


def test_new_strategies_get_catalysts_and_sectors():
    catalysts, sectors = {"2026-10-06": {"TCS": 0.5}}, {"TCS": "IT"}
    by_name = {s.spec.name: s for s in build_default_strategies(universe=["TCS"], catalysts=catalysts, sector_of=sectors)}
    assert by_name["gap_and_go"].catalysts == catalysts and by_name["gap_fill_fade"].catalysts == catalysts
    assert by_name["relative_strength_sector"].sector_of == sectors
    assert "trend_day_pullback" in by_name
