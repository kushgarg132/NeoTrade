"""The bar-by-bar engine loop shared by backtest, paper, and (later) live
trading. Only the injected DataFeed/ExecutionClient/Clock differ between
them -- this function and the Strategy contract it drives don't change.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from backend.ai.sentiment import get_cached_sentiment
from backend.components.risk.risk import RiskRules
from backend.core.clock import Clock, SimClock
from backend.core.models import Intent, Order, Side
from backend.engine.context import SimpleStrategyContext
from backend.engine.persistence import LedgerStore
from backend.engine.portfolio import Portfolio
from backend.engine.protocols import DataFeed, ExecutionClient, Strategy, StrategyContext
from backend.engine.session import IST, is_past_square_off_time
from backend.instruments.master import InstrumentMaster
from backend.learning.adapt import LearnedRules
from backend.options.sizing import size_option_intent
from backend.risk.kill_switch import should_trip
from backend.engine.execution.costs import calculate_indian_costs
from backend.scoring.composite import CompositeScore, score_intent

logger = logging.getLogger(__name__)


def entry_context(intent: Intent, scored: CompositeScore) -> dict:
    """What the trade an order opens should remember about its signal --
    the same fields a suggestion stores (backend/suggestions/store.py)."""
    return {
        "strength": intent.strength,
        "reason_codes": list(intent.reason_codes),
        "score": {"rule": scored.rule_score, "ai": scored.ai_score, "final": scored.final},
        "stop": intent.stop_hint, "target": intent.target_hint,
    }


def _opens(intent: Intent, portfolio: Portfolio, mode: str) -> bool:
    """Whether `intent` adds risk rather than closing it. An option always
    opens; a long-term equity sell is always an exit (CNC cannot short)."""
    if intent.option_flavor is not None:
        return True
    pos = portfolio.positions.get(intent.symbol)
    held = pos.quantity if pos else 0.0
    if intent.side == Side.BUY:
        return held >= 0
    return mode == "INTRADAY" and held <= 0


@dataclass(frozen=True)
class Proposal:
    """A sized order plus the reasoning that produced it.

    The Order alone is not enough for anything downstream that has to explain
    itself to a person -- the conviction, the reason codes and the reference
    entry all live on the Intent and the score, and are lost the moment
    sizing hands back a bare Order.
    """
    order: Order
    intent: Intent
    score: CompositeScore
    entry: float
    mode: str
    # Populated only for an option_flavor'd Intent (Phase 5b):
    # strike/expiry/option_type/premium/margin/underlying_spot, so
    # SuggestionStore.create can persist a real contract without
    # re-deriving it. None for every ordinary equity Proposal.
    option_contract: Optional[dict] = None


# Returns True if the order should execute now, False if the sink took
# ownership of it instead (see backend/suggestions/sink.py).
OrderSink = Callable[[Proposal], Awaitable[bool]]

# % of account risked per trade at full conviction (scored.final == 1.0),
# scaled linearly down to 0 as conviction falls -- see size_intents' docstring.
BASE_RISK_PCT = 1.0
# An entry must expect at least this multiple of its round-trip friction.
COST_MULTIPLE = 3
FILTER_SLIPPAGE_BPS = 10.0  # per side, as the backtester assumes


async def size_intents(
    intents: list[Intent],
    portfolio: Portfolio,
    ctx: StrategyContext,
    owner_by_symbol: dict[str, Strategy],
    redis,
    account_size: float,
    max_exposure: float,
    order_sink: Optional[OrderSink] = None,
    per_trade_cap: Optional[float] = None,
    kill_switch_tripped: bool = False,
    master: Optional[InstrumentMaster] = None,
    premium_source=None,
    option_legs: Optional[dict[str, dict]] = None,
    learned: Optional[LearnedRules] = None,
    strategies_by_name: Optional[dict[str, Strategy]] = None,
    holders: Optional[dict[str, str]] = None,
    plan=None,
) -> list[Order]:
    """Scores each Intent (backend.scoring.composite.score_intent, which
    caps AI's influence at AI_CAP regardless of what's passed here), then
    sizes it via the existing fixed-fractional risk sizer
    (RiskRules.calculate_position_size).

    Conviction-to-risk formula: `risk_pct = BASE_RISK_PCT * scored.final`.
    scored.final is in [0, 1] (and in practice >= 0.7*RULE_FLOOR once the
    rule floor is met, since AI can only pull it down to neutral, never
    below the rule score's floor-gated contribution) -- so this scales the
    fraction of the account risked on this trade linearly with conviction:
    full conviction (final=1.0) risks BASE_RISK_PCT of the account on a
    stop-loss-defined loss; weaker-but-still-floor-passing conviction risks
    proportionally less. Linear scaling is the simplest choice that
    guarantees the required property: `calculate_position_size` is linear
    in `risk_per_trade_percent` for fixed entry/stop/account_size, so a
    strictly higher `scored.final` can never produce a smaller position,
    all else equal.

    An Intent whose rule floor isn't met scores None and produces no order.
    An Intent with no `stop_hint` cannot be sized (no risk-per-share to
    divide by) -- skipped and logged, never guessed.

    `current_exposure` is computed fresh from `portfolio.positions` each
    call (not threaded through as mutable state), then accumulated locally
    as orders are added within this same call so a burst of same-call
    intents can't jointly blow past `max_exposure` even though each looked
    fine against the pre-call snapshot alone.

    An INTRADAY option Intent (LONG_CALL / LONG_PUT) is only sized when the
    caller passes `option_legs`, the run's record of the option positions it
    must later close (see _option_exit_orders); each order made is added to
    it. One such trade per underlying per day, none after the square-off.
    """
    orders: list[Order] = []
    current_exposure = sum(
        abs(pos.quantity * pos.avg_price) for pos in portfolio.positions.values()
    )

    for intent in intents:
        ai_sentiment = await get_cached_sentiment(intent.symbol, redis) if redis is not None else None
        scored = score_intent(intent, ai_sentiment)
        if scored is None:
            continue  # rule floor not met -- no trade, regardless of AI

        # The strategy that emitted the intent owns it; the symbol's listed
        # owner is only a fallback for intents made outside a run.
        owning_strategy = (strategies_by_name or {}).get(intent.strategy) or owner_by_symbol.get(intent.symbol)
        mode = owning_strategy.spec.mode if owning_strategy is not None else "LONGTERM"

        # One owner per open position: only the strategy that opened it may
        # add to it or exit it; anyone else's signal waits until it is flat.
        held_pos = portfolio.positions.get(intent.symbol)
        holder = (holders or {}).get(intent.symbol)
        if (holder is not None and intent.strategy is not None and holder != intent.strategy
                and held_pos is not None and held_pos.quantity != 0):
            logger.info("skipping intent for %s: held by %s, not %s", intent.symbol, holder, intent.strategy)
            continue

        # What this user's own paper record taught (backend/learning/adapt.py).
        # Exits are never held back: only a signal that opens risk is judged.
        if learned is not None and _opens(intent, portfolio, mode):
            why = learned.blocks(owning_strategy.spec.name if owning_strategy is not None else None,
                                 intent.strength)
            if why:
                logger.info("skipping intent for %s: %s", intent.symbol, why)
                continue

        # Today's game plan (backend/plan/gate.py): only tightens, only for
        # intraday signals that open risk.
        if plan is not None and mode == "INTRADAY" and _opens(intent, portfolio, mode):
            held = portfolio.positions.get(intent.symbol)
            why = plan.blocks(
                owning_strategy.spec.name if owning_strategy is not None else intent.strategy, intent.symbol,
                holding=held is not None and held.quantity != 0,
                open_positions=sum(1 for p in portfolio.positions.values() if p.quantity != 0),
            )
            if why:
                logger.info("skipping intent for %s: %s", intent.symbol, why)
                continue

        # The kill-switch is about auto-executed risk. A tripped switch
        # blocks new INTRADAY orders (the ones that go straight to
        # execution) but not LONGTERM ones -- those stop at a
        # human-approved suggestion regardless, so blocking them too would
        # only hide information from the person reviewing the inbox.
        if kill_switch_tripped and mode == "INTRADAY":
            continue

        if intent.option_flavor is not None:
            intraday = mode == "INTRADAY"
            today = ctx.now().astimezone(IST).date()
            if intraday and (
                option_legs is None or is_past_square_off_time(ctx.now())
                or any(leg["underlying"] == intent.symbol and leg["day"] == today for leg in option_legs.values())
            ):
                continue
            result = await size_option_intent(intent, scored, ctx, account_size, master, premium_source)
            if result is None:
                continue
            if intraday and per_trade_cap is not None and result.margin_estimate > per_trade_cap:
                continue
            result.order.strategy_name = (
                owning_strategy.spec.name if owning_strategy is not None else None
            )
            result.order.context = entry_context(intent, scored)
            option_contract = {
                "strike": result.contract.strike,
                "expiry": result.contract.expiry.isoformat() if result.contract.expiry else None,
                "option_type": result.contract.instrument_type,
                "lot_size": result.contract.lot_size,
                "premium_estimate": result.premium_estimate,
                "premium_is_live": result.premium_is_live,
                "margin_estimate": result.margin_estimate,
                "underlying_spot": result.underlying_spot,
            }
            if order_sink is not None:
                proposal = Proposal(
                    order=result.order, intent=intent, score=scored,
                    entry=result.premium_estimate, mode=mode, option_contract=option_contract,
                )
                if not await order_sink(proposal):
                    continue
            if intraday:
                option_legs[result.order.symbol] = {
                    "underlying": intent.symbol, "day": today, "contract": result.contract,
                    "bullish": intent.option_flavor == "LONG_CALL",
                    "stop": intent.stop_hint, "target": intent.target_hint,
                    "mark": result.premium_estimate, "strategy_name": result.order.strategy_name,
                }
            orders.append(result.order)
            continue

        if intent.stop_hint is None:
            logger.info("skipping intent for %s: strategy supplied no stop_hint", intent.symbol)
            continue

        history = ctx.history(intent.symbol, 1)
        if not history:
            logger.info("skipping intent for %s: no known price yet this run", intent.symbol)
            continue
        entry = history[-1].close
        stop = intent.stop_hint

        risk_pct = BASE_RISK_PCT * scored.final * (plan.multiplier if plan is not None and mode == "INTRADAY" else 1.0)
        raw_size = RiskRules.calculate_position_size(account_size, risk_pct, entry, stop)
        # NSE cash equity delivery/intraday trades in whole shares only.
        size = float(int(raw_size))
        if size <= 0:
            continue

        # The per-trade cap bounds what one stock may hold: an entry is
        # trimmed to the room left under it, as the long-term path trims
        # (autorun.py), rather than dropped -- risk sizing with a tight
        # intraday stop lands far above a small account's cap. An exit is
        # never trimmed: the cap limits risk taken, not risk closed.
        if per_trade_cap is not None and _opens(intent, portfolio, mode):
            pos = portfolio.positions.get(intent.symbol)
            room = per_trade_cap - (abs(pos.quantity * pos.avg_price) if pos else 0.0)
            if size * entry > room:
                trimmed = float(int(max(room, 0.0) // entry))
                logger.info(
                    "trimming %s from %g to %g shares: %.2f room left under the per-trade cap %.2f",
                    intent.symbol, size, trimmed, max(room, 0.0), per_trade_cap,
                )
                size = trimmed
                if size <= 0:
                    continue
        notional = size * entry
        # Cost filter: an entry whose target cannot beat COST_MULTIPLE x its
        # round-trip friction (charges both ways + slippage) cannot win after
        # costs. Exits are never filtered; an intent with no target is not judged.
        if intent.target_hint is not None and _opens(intent, portfolio, mode):
            product_for_cost = "MIS" if mode == "INTRADAY" else "CNC"
            gain = (intent.target_hint - entry if intent.side == Side.BUY else entry - intent.target_hint) * size
            friction = (
                calculate_indian_costs(entry, size, Side.BUY, product_for_cost)
                + calculate_indian_costs(entry, size, Side.SELL, product_for_cost)
                + notional * 2 * FILTER_SLIPPAGE_BPS / 10_000
            )
            if gain < COST_MULTIPLE * friction:
                logger.info("skipping intent for %s: expected ₹%.2f < %d x friction ₹%.2f",
                            intent.symbol, gain, COST_MULTIPLE, friction)
                continue
        if not RiskRules.check_exposure_limit(current_exposure, max_exposure, notional):
            continue
        current_exposure += notional

        product = "MIS" if mode == "INTRADAY" else "CNC"

        order = Order(
            id=str(uuid.uuid4()),
            symbol=intent.symbol,
            side=intent.side,
            quantity=size,
            order_type="MARKET",
            limit_price=None,
            product=product,
            strategy_name=owning_strategy.spec.name if owning_strategy is not None else None,
            context=entry_context(intent, scored),
        )

        if order_sink is not None:
            proposal = Proposal(order=order, intent=intent, score=scored, entry=entry, mode=mode)
            if not await order_sink(proposal):
                continue  # the sink owns it now -- e.g. it became a suggestion

        orders.append(order)

    return orders


def _square_off_orders(
    bar_symbol: Optional[str],
    bar_timestamp,
    portfolio: Portfolio,
    owner_by_symbol: dict[str, Strategy],
) -> list[Order]:
    """MIS intraday square-off: if the strategy owning `bar_symbol` trades
    INTRADAY and the current bar is at/past 15:15 IST with an open
    position still held, force a closing MARKET order. Keyed purely off the
    bar's own timestamp, so this applies identically to a live/polling feed
    running in real time and to a HistoricalFeed backtest replaying bars
    past that time of day.
    """
    if bar_symbol is None:
        return []
    owning_strategy = owner_by_symbol.get(bar_symbol)
    if owning_strategy is None or owning_strategy.spec.mode != "INTRADAY":
        return []
    if not is_past_square_off_time(bar_timestamp):
        return []

    position = portfolio.positions.get(bar_symbol)
    if position is None or position.quantity == 0:
        return []

    closing_side = Side.SELL if position.quantity > 0 else Side.BUY
    return [Order(
        id=str(uuid.uuid4()),
        symbol=bar_symbol,
        side=closing_side,
        quantity=abs(position.quantity),
        order_type="MARKET",
        limit_price=None,
        product="MIS",
    )]


async def _option_exit_orders(
    bar_symbol: Optional[str],
    bar,
    portfolio: Portfolio,
    option_legs: dict[str, dict],
    premium_source,
) -> list[Order]:
    """Closes a bought intraday option when its underlying (`bar_symbol`)
    reaches the stop or target the strategy set on it, or at the 15:15
    square-off. Every open leg on this underlying is repriced first, so its
    `mark` is the premium an exit fills at and what the kill-switch counts.
    ponytail: a leg whose repricing fails keeps its last mark, and a paper
    exit fills at that stale premium; a live leg fills at the broker's own
    price regardless."""
    orders = []
    for symbol, leg in option_legs.items():
        position = portfolio.positions.get(symbol)
        if leg["underlying"] != bar_symbol or position is None or position.quantity <= 0:
            continue
        if premium_source is not None and (premium := await premium_source(leg["contract"])) is not None:
            leg["mark"] = premium
        price = bar.close
        stopped = price <= leg["stop"] if leg["bullish"] else price >= leg["stop"]
        reached = price >= leg["target"] if leg["bullish"] else price <= leg["target"]
        if stopped or reached or is_past_square_off_time(bar.timestamp):
            orders.append(Order(
                id=str(uuid.uuid4()), symbol=symbol, side=Side.SELL, quantity=position.quantity,
                order_type="MARKET", limit_price=None, product="MIS",
                strategy_name=leg["strategy_name"], contract=leg["contract"],
            ))
    return orders


async def run(
    strategies: list[Strategy],
    feed: DataFeed,
    execution: ExecutionClient,
    portfolio: Portfolio,
    clock: Clock,
    symbol_for_token: Optional[dict[int, str]] = None,
    redis=None,
    account_size: float = 1_000_000.0,
    max_exposure: float = 1_000_000.0,
    ledger: Optional[LedgerStore] = None,
    order_sink: Optional[OrderSink] = None,
    per_trade_cap: Optional[float] = None,
    daily_loss_limit: Optional[float] = None,
    kill_switch_store=None,
    master: Optional[InstrumentMaster] = None,
    premium_source=None,
    on_progress: Optional[Callable[[dict], Awaitable[None]]] = None,
    holders: Optional[dict[str, str]] = None,
    learned: Optional[LearnedRules] = None,
    plan=None,
) -> None:
    """`symbol_for_token` is not in the plan's pseudocode signature; it's
    needed because `Bar` identifies instruments by `instrument_token` while
    Strategy/Intent/Order/StrategySpec.universe all work in tradingsymbol
    strings, and no protocol in this task carries that mapping on its own.
    Callers that already resolved an Instrument list (e.g.
    `backtest.run_backtest`) build it once and pass it in; `HistoricalFeed`
    also exposes it as `.symbol_for_token` for convenience.

    `redis`/`account_size`/`max_exposure` feed `size_intents` (Task 6);
    `redis=None` means sentiment is treated as neutral for every intent
    (same as a cache miss) rather than crashing -- lets backtests run
    without a Redis dependency. `ledger`, if given, mirrors every
    order/fill/position snapshot into Mongo (backend/engine/persistence.py)
    alongside the in-memory `portfolio`, which remains the book of record.

    `daily_loss_limit`/`kill_switch_store` (Phase 3): when both are given,
    each bar's cumulative realized+unrealized P&L (`portfolio.equity`) is
    checked against the limit; a breach persists a trip
    (`backend.risk.kill_switch.KillSwitchStore`, keyed by `ledger.user_id`
    and the bar's IST calendar date -- so `ledger` must also be given for
    this to do anything) and blocks further INTRADAY orders for the rest of
    this run. `kill_switch_store` is checked once at the start too, so a
    run restarted after an earlier trip today starts blocked rather than
    getting a fresh chance to lose more before re-detecting the breach.
    Omit either argument and the kill-switch simply never engages, exactly
    as before this parameter existed.

    `on_progress`, if given, is awaited after every bar with running counts
    (bars seen, signals raised, orders sent, the last bar's symbol and time)
    so a live run can show it is alive. Throttling is the caller's job.
    """
    symbol_for_token = symbol_for_token or {}
    ctx = SimpleStrategyContext(clock, portfolio, symbol_for_token)
    owner_by_symbol = {
        symbol: strategy for strategy in strategies for symbol in strategy.spec.universe
    }
    strategies_by_name = {strategy.spec.name: strategy for strategy in strategies}
    # symbol -> name of the strategy whose fill opened the open position;
    # seeded with what an earlier run of today left open (engine/adopt.py).
    holders = dict(holders or {})
    strategy_of_order: dict[str, str] = {}

    for strategy in strategies:
        strategy.on_start(ctx)

    kill_switch_tripped = False
    option_legs: dict[str, dict] = {}
    progress = {"bars": 0, "signals": 0, "orders": 0, "last_symbol": None, "last_bar_at": None}

    async for bar in feed:
        if isinstance(clock, SimClock):
            clock.advance(bar.timestamp)
        ctx.update(bar)

        symbol = symbol_for_token.get(bar.instrument_token)

        if daily_loss_limit is not None and kill_switch_store is not None and ledger is not None:
            trading_day = bar.timestamp.astimezone(IST).date()
            if not kill_switch_tripped:
                if await kill_switch_store.is_tripped(ledger.user_id, trading_day):
                    kill_switch_tripped = True
                else:
                    mark_prices = {
                        pos_symbol: history[-1].close
                        for pos_symbol in portfolio.positions
                        if (history := ctx.history(pos_symbol, 1))
                    }
                    mark_prices.update({s: leg["mark"] for s, leg in option_legs.items()})
                    equity = portfolio.equity(mark_prices)
                    if should_trip(equity, daily_loss_limit):
                        kill_switch_tripped = True
                        await kill_switch_store.trip(
                            ledger.user_id, trading_day,
                            reason=f"daily loss limit ₹{daily_loss_limit:,.0f} breached",
                            equity=equity,
                        )

        # SimulatedExecutionClient (and any future ExecutionClient that
        # fills against the current bar rather than a live broker feed)
        # needs to know the current price; this isn't part of the shared
        # ExecutionClient protocol since a real broker client wouldn't need
        # it, so it's a best-effort duck-typed hook.
        if symbol is not None and hasattr(execution, "on_bar"):
            execution.on_bar(symbol, bar)

        if symbol is not None:
            for strategy in strategies:
                if symbol in strategy.spec.universe and bar.timeframe == strategy.spec.timeframe:
                    ctx.current_strategy = strategy.spec.name
                    try:
                        strategy.on_bar(ctx, bar)
                    finally:
                        ctx.current_strategy = None

        intents = ctx.drain_intents()
        if bar.warmup:
            # A catch-up bar (a restarted run's first poll): the strategies
            # have seen it, but its price is hours old -- no order on it.
            intents, orders = [], []
        else:
            if plan is not None:
                await plan.refresh(bar.timestamp)
            orders = await size_intents(
                intents, portfolio, ctx, owner_by_symbol, redis, account_size, max_exposure,
                order_sink=order_sink, per_trade_cap=per_trade_cap, kill_switch_tripped=kill_switch_tripped,
                master=master, premium_source=premium_source, option_legs=option_legs, learned=learned,
                plan=plan,
                strategies_by_name=strategies_by_name, holders=holders,
            )
            held_by = {**owner_by_symbol, **{s: strategies_by_name[h] for s, h in holders.items() if h in strategies_by_name}}
            orders.extend(_square_off_orders(symbol, bar.timestamp, portfolio, held_by))
            orders.extend(await _option_exit_orders(symbol, bar, portfolio, option_legs, premium_source))

        for order in orders:
            # An option has no bar of its own: paper fills it at the
            # premium last read for it.
            if order.symbol in option_legs and hasattr(execution, "mark"):
                execution.mark(order.symbol, option_legs[order.symbol]["mark"], bar.timestamp)
            if ledger is not None:
                await ledger.record_order(order)
            if order.strategy_name:
                strategy_of_order[order.id] = order.strategy_name
            await execution.submit(order)

        # A live ExecutionClient (BrokerExecutionClient/RoutingExecutionClient,
        # backend/engine/execution/broker.py, .../routing.py) needs to poll the
        # broker for order-status changes; this isn't part of the shared
        # ExecutionClient protocol since paper trading doesn't need it, so
        # it's a best-effort duck-typed hook, same convention as on_bar
        # above. Runs once per bar -- for a live/polling feed that's the
        # feed's own poll_interval_seconds cadence, reused rather than
        # inventing a second background task.
        if hasattr(execution, "poll_once"):
            await execution.poll_once()

        async for fill in execution.fills():
            quantity_before = portfolio.positions[fill.symbol].quantity if fill.symbol in portfolio.positions else 0.0
            portfolio.apply(fill)
            if ledger is not None:
                await ledger.on_fill(fill, quantity_before, portfolio.positions[fill.symbol])
            name = strategy_of_order.get(fill.order_id) or holders.get(fill.symbol)
            after = portfolio.positions[fill.symbol].quantity
            if after == 0:
                holders.pop(fill.symbol, None)
            elif quantity_before == 0 or (quantity_before > 0) != (after > 0):
                if name is not None:
                    holders[fill.symbol] = name  # opened (or flipped) by this strategy
            owning_strategy = strategies_by_name.get(name) or owner_by_symbol.get(fill.symbol)
            if owning_strategy is not None:
                owning_strategy.on_fill(ctx, fill)

        if ledger is not None:
            await ledger.snapshot_positions(portfolio.positions)

        if on_progress is not None:
            progress["bars"] += 1
            progress["signals"] += len(intents)
            progress["orders"] += len(orders)
            progress["last_symbol"] = symbol
            progress["last_bar_at"] = bar.timestamp
            await on_progress(dict(progress))
