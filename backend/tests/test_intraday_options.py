"""Options step 3: the intraday options strategy on paper. A LONG_CALL /
LONG_PUT intent buys a real at-the-money contract at its live premium, and
the runner closes it when the underlying reaches the stop or target, or at
the 15:15 square-off -- filled at the premium read at that moment."""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.clock import SimClock
from backend.core.models import Bar, Intent, Order, Side
from backend.engine.execution.routing import RoutingExecutionClient
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import StrategySpec
from backend.engine.runner import run
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.strategies.intraday.orb_options import ORBOptionsStrategy

TOKEN = 1
START = datetime(2024, 12, 2, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
CALL = "RELIANCE24DEC100CE"


class _BuyCallOnce:
    """Asks for a call on every bar once 20 bars of history exist -- the
    runner, not the strategy, must hold it to one trade a day."""

    def __init__(self, flavor: str = "LONG_CALL") -> None:
        self.flavor = flavor
        self.spec = StrategySpec(name="orb_options", mode="INTRADAY", timeframe="5m",
                                 warmup_bars=0, universe=["RELIANCE"])

    def on_start(self, ctx) -> None:
        pass

    def on_bar(self, ctx, bar) -> None:
        if len(ctx.history("RELIANCE", 20)) == 20:
            bullish = self.flavor == "LONG_CALL"
            ctx.submit(Intent(
                symbol="RELIANCE", side=Side.BUY, strength=1.0, reason_codes=["test"],
                stop_hint=95.0 if bullish else 105.0, target_hint=110.0 if bullish else 90.0,
                option_flavor=self.flavor,
            ))

    def on_fill(self, ctx, fill) -> None:
        pass


def _bars(closes: list[float], start: datetime = START):
    async def feed():
        for i, close in enumerate(closes):
            yield Bar(instrument_token=TOKEN, timeframe="5m", timestamp=start + timedelta(minutes=5 * i),
                      open=close, high=close, low=close, close=close, volume=1000.0)
    return feed()


async def _master() -> InstrumentMaster:
    master = InstrumentMaster(AsyncMongoMockClient()["test_db"])
    await master.upsert_many([
        Instrument(
            exchange="NFO", tradingsymbol=f"RELIANCE24DEC{strike}{kind}", name="RELIANCE",
            instrument_token=10 + i, exchange_token=10 + i, instrument_type=kind, segment="NFO-OPT",
            lot_size=250, tick_size=0.05, expiry=datetime(2024, 12, 5), strike=float(strike),
        )
        for i, (strike, kind) in enumerate([(95, "CE"), (100, "CE"), (105, "CE"), (100, "PE")])
    ])
    return master


class _Premiums:
    def __init__(self, price: float) -> None:
        self.price = price

    async def __call__(self, contract):
        return self.price


async def _run(strategy, closes, premiums, start=START, execution=None):
    execution = execution or SimulatedExecutionClient()
    portfolio = Portfolio()
    fills = []
    original = execution.fills

    async def recording():
        async for fill in original():
            fills.append(fill)
            yield fill
    execution.fills = recording

    feed = _bars(closes, start)
    # Premium moves with the underlying: 5 at 100, one rupee per rupee.
    async def priced():
        async for bar in feed:
            premiums.price = 5.0 + (bar.close - 100.0)
            yield bar
    await run(
        strategies=[strategy], feed=priced(), execution=execution, portfolio=portfolio,
        clock=SimClock(), symbol_for_token={TOKEN: "RELIANCE"},
        master=await _master(), premium_source=premiums,
    )
    return portfolio, fills


@pytest.mark.asyncio
async def test_buys_the_atm_call_at_its_live_premium_and_exits_at_target():
    portfolio, fills = await _run(_BuyCallOnce(), [100.0] * 20 + [104.0, 111.0, 111.0, 111.0], _Premiums(5.0))

    entry, exit_ = fills
    assert entry.symbol == exit_.symbol == CALL
    assert entry.side == Side.BUY and entry.price == 5.0
    assert exit_.side == Side.SELL and exit_.price == 16.0
    assert entry.quantity % 250 == 0 and entry.quantity > 0
    assert entry.costs > 0  # options cost model, not zero
    position = portfolio.positions[CALL]
    assert position.quantity == 0
    assert position.realized_pnl == pytest.approx(11.0 * entry.quantity)


@pytest.mark.asyncio
async def test_put_exits_at_the_underlying_stop():
    _portfolio, fills = await _run(_BuyCallOnce("LONG_PUT"), [100.0] * 20 + [106.0, 106.0], _Premiums(5.0))

    entry, exit_ = fills
    assert entry.symbol == exit_.symbol == "RELIANCE24DEC100PE"
    assert exit_.side == Side.SELL and exit_.quantity == entry.quantity


@pytest.mark.asyncio
async def test_squares_off_at_1515_ist():
    start = datetime(2024, 12, 2, 8, 0, tzinfo=timezone.utc)  # 13:30 IST; bar 21 is 15:15
    _portfolio, fills = await _run(_BuyCallOnce(), [100.0] * 22, _Premiums(5.0), start=start)

    assert [f.side for f in fills] == [Side.BUY, Side.SELL]
    assert fills[1].timestamp.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%H:%M") == "15:15"


@pytest.mark.asyncio
async def test_no_trade_without_a_live_premium():
    _portfolio, fills = await _run(_BuyCallOnce(), [100.0] * 24, _NoPremium())
    assert fills == []


class _NoPremium(_Premiums):
    def __init__(self) -> None:
        super().__init__(0.0)

    async def __call__(self, contract):
        return None


@pytest.mark.asyncio
async def test_routing_keeps_option_orders_on_paper():
    class _Live:
        async def submit(self, order):
            raise AssertionError("an option order reached the broker")

    paper = SimulatedExecutionClient()
    routing = RoutingExecutionClient(paper=paper, live_by_strategy={"orb_options": _Live()})
    routing.mark(CALL, 5.0, START, option=True)
    order = Order(id="1", symbol=CALL, side=Side.BUY, quantity=250, order_type="MARKET",
                  strategy_name="orb_options")
    assert await routing.submit(order) == "1"


def test_orb_options_turns_a_breakdown_into_a_bought_put(monkeypatch):
    strategy = ORBOptionsStrategy(["RELIANCE", "IRCTC"], {1: "RELIANCE", 2: "IRCTC"})
    signal = Intent(symbol="RELIANCE", side=Side.SELL, strength=0.65, reason_codes=["orb_breakout"],
                    stop_hint=105.0, target_hint=90.0)
    monkeypatch.setattr(strategy, "signal", lambda ctx, symbol: signal)
    submitted = []
    ctx = type("Ctx", (), {"submit": lambda self, intent: submitted.append(intent)})()

    strategy.on_bar(ctx, Bar(instrument_token=1, timeframe="5m", timestamp=START,
                             open=1, high=1, low=1, close=1, volume=1))
    strategy.on_bar(ctx, Bar(instrument_token=2, timeframe="5m", timestamp=START,
                             open=1, high=1, low=1, close=1, volume=1))  # not F&O-eligible

    (intent,) = submitted
    assert intent.side == Side.BUY and intent.option_flavor == "LONG_PUT"
    assert intent.reason_codes == ["orb_breakout", "buy_put"]
    assert (intent.stop_hint, intent.target_hint) == (105.0, 90.0)
