from datetime import datetime, timedelta, timezone

from backend.core.clock import SimClock
from backend.core.models import Bar, Side
from backend.engine.context import SimpleStrategyContext
from backend.engine.portfolio import Portfolio
from backend.strategies.intraday.gap_and_go import GapAndGoStrategy

SYMBOL, TOKEN = "TEST", 111
PRIOR, TODAY = datetime(2026, 10, 5, 3, 45, tzinfo=timezone.utc), datetime(2026, 10, 6, 3, 45, tzinfo=timezone.utc)


def _session(start, rows):
    """rows: (open, high, low, close, volume) per 5-minute bar."""
    return [Bar(instrument_token=TOKEN, timeframe="5m", timestamp=start + i * timedelta(minutes=5),
                open=o, high=h, low=l, close=c, volume=v) for i, (o, h, l, c, v) in enumerate(rows)]


def _prior():
    return _session(PRIOR, [(100, 101, 99, 100, 1000)] * 10)


def _up_day(post_low=103.0):
    return _session(TODAY, [
        (103, 104, 102.5, 103.5, 1000), (103.5, 104, 103, 103.2, 1000), (103.2, 104, 103, 103.6, 1000),
        (103.6, 103.9, post_low, 103.8, 1000), (103.8, 103.9, 103.2, 103.8, 1000),
        (103.8, 105.2, 103.7, 105, 5000),
    ])


def _down_day():
    return _session(TODAY, [
        (97, 97.5, 96, 96.5, 1000), (96.5, 97, 96.2, 96.8, 1000), (96.8, 97.2, 96.3, 96.4, 1000),
        (96.4, 97, 96.2, 96.5, 1000), (96.5, 96.9, 96.2, 96.3, 1000),
        (96.3, 96.4, 94.8, 95, 5000),
    ])


def _run(strategy, bars):
    ctx = SimpleStrategyContext(SimClock(), Portfolio(), {TOKEN: SYMBOL})
    for bar in bars:
        ctx.update(bar)
    strategy.on_bar(ctx, bars[-1])
    return ctx.drain_intents()


def _gap_and_go(catalysts):
    return GapAndGoStrategy([SYMBOL], {TOKEN: SYMBOL}, catalysts=catalysts)


def test_gap_and_go_buys_a_catalysed_gap_that_breaks_its_range():
    intents = _run(_gap_and_go({"2026-10-06": {SYMBOL: 0.7}}), _prior() + _up_day())
    assert len(intents) == 1
    intent = intents[0]
    assert intent.side == Side.BUY and intent.reason_codes == ["gap_and_go", "news_catalyst"]
    assert intent.stop_hint == 102.5 and intent.target_hint == 105 + 2 * (105 - 102.5)


def test_gap_and_go_sells_a_negative_catalysed_gap_down():
    intents = _run(_gap_and_go({"2026-10-06": {SYMBOL: -0.6}}), _prior() + _down_day())
    assert [i.side for i in intents] == [Side.SELL]
    assert intents[0].stop_hint == 97.5


def test_gap_and_go_silent_without_catalyst_or_on_another_days_catalyst():
    assert _run(_gap_and_go({}), _prior() + _up_day()) == []
    assert _run(_gap_and_go({"2026-10-05": {SYMBOL: 0.7}}), _prior() + _up_day()) == []


def test_gap_and_go_silent_on_the_first_session_in_history():
    assert _run(_gap_and_go({"2026-10-06": {SYMBOL: 0.7}}), _up_day()) == []


def test_gap_and_go_silent_when_range_low_broken_first():
    assert _run(_gap_and_go({"2026-10-06": {SYMBOL: 0.7}}), _prior() + _up_day(post_low=102.0)) == []
