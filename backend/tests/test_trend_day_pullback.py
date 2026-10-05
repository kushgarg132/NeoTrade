from datetime import datetime, timedelta, timezone

from backend.core.clock import SimClock
from backend.core.models import Bar, Side
from backend.engine.context import SimpleStrategyContext
from backend.engine.portfolio import Portfolio
from backend.strategies.intraday.trend_day_pullback import TrendDayPullbackStrategy

SYMBOL, TOKEN = "TEST", 111
START = datetime(2026, 10, 6, 3, 45, tzinfo=timezone.utc)


def _bars(rows):
    """rows: (open, high, low, close)."""
    return [Bar(instrument_token=TOKEN, timeframe="5m", timestamp=START + i * timedelta(minutes=5),
                open=o, high=h, low=l, close=c, volume=1000) for i, (o, h, l, c) in enumerate(rows)]


def _trend(sign=1, pullback=True):
    """14 bars trending 0.3 a bar, then (optionally) a dip into the EMAs
    that holds, then a bar clearing the dip's extreme. sign=-1 mirrors it."""
    f = (lambda x: x) if sign > 0 else (lambda x: 200 - x)
    rows = [(f(o), max(f(h), f(l)), min(f(h), f(l)), f(cl)) for o, h, l, cl in
            [(100 + 0.3 * i - 0.3, 100 + 0.3 * i + 0.1, 100 + 0.3 * i - 0.1, 100 + 0.3 * i) for i in range(14)]]
    last = 100 + 0.3 * 13
    if pullback:
        dip = (last, last, last - 1.5, last - 0.4)
        go = (last - 0.4, last + 0.6, last - 0.4, last + 0.5)
    else:
        dip = (last, last + 0.4, last - 0.1, last + 0.3)
        go = (last + 0.3, last + 0.7, last + 0.2, last + 0.6)
    for o, h, l, cl in (dip, go):
        rows.append((f(o), max(f(h), f(l)), min(f(h), f(l)), f(cl)))
    return _bars(rows)


def _run(bars):
    strategy = TrendDayPullbackStrategy([SYMBOL], {TOKEN: SYMBOL})
    ctx = SimpleStrategyContext(SimClock(), Portfolio(), {TOKEN: SYMBOL})
    for bar in bars:
        ctx.update(bar)
    strategy.on_bar(ctx, bars[-1])
    return ctx.drain_intents()


def test_first_pullback_on_a_rising_day_is_bought():
    intents = _run(_trend())
    assert [i.side for i in intents] == [Side.BUY]
    assert intents[0].reason_codes == ["trend_day_pullback"]
    assert intents[0].stop_hint < intents[0].target_hint and intents[0].stop_hint < _trend()[-1].close


def test_first_rally_on_a_falling_day_is_sold():
    intents = _run(_trend(sign=-1))
    assert [i.side for i in intents] == [Side.SELL]
    assert intents[0].stop_hint > _trend(sign=-1)[-1].close


def test_silent_on_a_flat_day():
    assert _run(_bars([(100, 100.1, 99.9, 100)] * 20)) == []


def test_silent_on_a_trend_without_a_pullback():
    assert _run(_trend(pullback=False)) == []
