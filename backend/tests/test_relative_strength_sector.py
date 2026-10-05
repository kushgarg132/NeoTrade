from datetime import datetime, timedelta, timezone

from backend.core.clock import SimClock
from backend.core.models import Bar, Side
from backend.engine.context import SimpleStrategyContext
from backend.engine.portfolio import Portfolio
from backend.strategies.intraday.relative_strength_sector import RelativeStrengthSectorStrategy

START = datetime(2026, 10, 6, 3, 45, tzinfo=timezone.utc)
TOKENS = {111: "LEAD", 112: "P1", 113: "P2", 114: "P3"}
SECTORS = {s: "IT" for s in TOKENS.values()}


def _series(token, closes):
    bars, prev = [], 100.0
    for i, c in enumerate(closes):
        bars.append(Bar(instrument_token=token, timeframe="5m", timestamp=START + i * timedelta(minutes=5),
                        open=prev, high=max(prev, c) + 0.1, low=min(prev, c) - 0.1, close=c, volume=1000))
        prev = c
    return bars


def _peers(sign, tokens=(112, 113, 114)):
    closes = [100 + sign * 0.1 * (i + 1) for i in range(8)]  # ends +-0.8%
    return [b for t in tokens for b in _series(t, closes)]


def _leader(sign):
    path = [0.5, 1.0, 1.5, 2.0, 2.3, 2.5, 2.2, 2.8]
    return _series(111, [100 + sign * p for p in path])


def _run(bars, sector_of=SECTORS):
    strategy = RelativeStrengthSectorStrategy(list(TOKENS.values()), TOKENS, sector_of=sector_of)
    ctx = SimpleStrategyContext(SimClock(), Portfolio(), TOKENS)
    for bar in bars:
        ctx.update(bar)
    strategy.on_bar(ctx, bars[-1])
    return ctx.drain_intents()


def test_leader_of_a_rising_sector_is_bought_on_a_pullback():
    intents = _run(_peers(1) + _leader(1))
    assert [(i.symbol, i.side) for i in intents] == [("LEAD", Side.BUY)]
    assert intents[0].reason_codes == ["relative_strength_sector"]
    assert intents[0].stop_hint == _leader(1)[-2].low


def test_laggard_of_a_falling_sector_is_sold():
    intents = _run(_peers(-1) + _leader(-1))
    assert [(i.symbol, i.side) for i in intents] == [("LEAD", Side.SELL)]
    assert intents[0].stop_hint == _leader(-1)[-2].high


def test_silent_with_too_few_peers_trading_today():
    assert _run(_peers(1, tokens=(112, 113)) + _leader(1)) == []


def test_silent_for_a_symbol_with_no_sector():
    assert _run(_peers(1) + _leader(1), sector_of={s: "IT" for s in ("P1", "P2", "P3")}) == []
