"""Every autopilot order passes this or is refused. Pure, no I/O.

Entries (buys) must respect every limit and need the switch on; an exit
(selling a symbol the autopilot holds) only needs the market open -- getting
out is never blocked by a cap or by the switch being off, so turning the
autopilot off never strands a position. Short selling is not allowed.

The market backdrop only ever tightens entries
(docs/superpowers/specs/2026-10-05-autopilot-news-design.md): risk-off
halves the per-trade cap and refuses news-triggered entries, and a
high-impact economic event within 30 minutes refuses every entry. No
regime (the ingest worker is down) adds no rule."""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from backend.core.models import Side

PRODUCTS = {"CNC", "MIS"}
NEWS_ENTRIES_PER_DAY = 3
# Strategies with no measured edge (trading-edge audit 2026-10-24): no new autopilot entries; exits stay open.
PARKED = frozenset({"analyst_verdict", "technical_breakout", "macd_crossover", "mean_reversion",
                    "trend_day_pullback", "gap_fill_fade", "relative_strength_sector"})
COST_MULTIPLE = 1.5  # an entry's expected gain must clear this many times its round-trip cost
# Automated entries: an engine/news idea needs its strategy's latest backtest gate passed (an
# allowlist; PARKED was a denylist that let any new strategy through), and no automated buy may
# pay more than MAX_COST_SHARE of its size in round-trip charges (2026-10-28: ~₹1,500 lots paid 1.56%).
BACKTESTED_SOURCES = {"engine", "news"}
AUTO_SOURCES = {"engine", "news", "picks"}
MAX_COST_SHARE = 0.01


@dataclass
class FenceState:
    deployed: float                # rupees in open autopilot positions, at mark
    entries_today: int
    held: dict = field(default_factory=dict)  # symbol -> (quantity, product) the autopilot holds
    others: frozenset = frozenset()  # symbols another strategy holds in the same book
    kill_tripped: bool = False
    session_ok: bool = True
    regime: Optional[str] = None   # market:regime label: risk_on / neutral / risk_off
    event_soon: bool = False       # a high-impact economic event within 30 minutes
    news_today: int = 0            # news-triggered entries today
    paused: frozenset = frozenset()  # strategies auto-retired on paper (learning/adapt.py)
    backtested: frozenset = frozenset()  # strategies whose latest backtest gate passed (risk/backtest_gate.py)


def trade_cap(prefs: dict, regime: Optional[str]) -> float:
    """The per-trade cap in force: halved while the market is risk-off."""
    return prefs["per_trade_cap"] / (2 if regime == "risk_off" else 1)


def round_trip_cost(price: float, quantity: float, product: str) -> float:
    """Charges on both sides at `price` plus the study's slippage both ways (lab/assumptions.py)."""
    from backend.engine.execution.costs import fill_costs
    from backend.lab.assumptions import DEFAULT

    slippage = 2 * price * quantity * DEFAULT.slippage_bps / 10_000
    return fill_costs(price, quantity, Side.BUY, product, False) + fill_costs(price, quantity, Side.SELL, product, False) + slippage


@lru_cache(maxsize=1)
def universe() -> frozenset:
    from backend.factor.data import universe as nifty200
    return frozenset(nifty200())


def check(order, price: float, state: FenceState, prefs: dict) -> Optional[str]:
    """None if the order may go, else why not (shown to the user)."""
    if not state.session_ok:
        return "The market is closed."
    if order.product not in PRODUCTS:
        return "The autopilot trades NSE equity only (CNC or MIS)."
    if order.quantity <= 0:
        return "The quantity must be a whole number above zero."
    if order.side == Side.SELL:
        # Only what the autopilot holds, in the product it holds it: never a short.
        quantity, product = state.held.get(order.symbol, (0, None))
        if quantity <= 0:
            return "The autopilot does not short sell."
        if order.quantity > quantity or order.product != product:
            return f"The autopilot holds {quantity:g} {order.symbol} ({product}); it can sell at most that."
        return None
    if not prefs.get("autopilot_enabled"):
        return "The autopilot is off."
    strategy = getattr(order, "strategy", None) or ""
    if strategy in PARKED or strategy.startswith("built:"):
        return "strategy parked: no edge (audit 2026-10-24)"
    if strategy in state.paused:
        return "strategy paused: losing on paper over 30+ trades"
    if order.source in BACKTESTED_SOURCES and strategy not in state.backtested:
        return "strategy unproven: no passed backtest gate"
    notional = price * order.quantity
    if state.kill_tripped:
        return "The daily loss limit was hit: no new entries today."
    if state.event_soon:
        return "A high-impact economic event is due within 30 minutes: no new entries until it is out."
    if order.source == "news":
        if not prefs.get("autopilot_news"):
            return "News-triggered trades are off."
        if state.regime == "risk_off":
            return "The market is risk-off: no news-triggered entries."
        if state.news_today >= NEWS_ENTRIES_PER_DAY:
            return f"Already {state.news_today} news-triggered trades today (limit {NEWS_ENTRIES_PER_DAY})."
    if order.symbol not in universe():
        return f"{order.symbol} is outside the autopilot's universe (Nifty 200)."
    if order.symbol in state.held:
        return f"The autopilot is already holding {order.symbol}."
    if order.symbol in state.others:
        return f"The AI's paper engine already holds {order.symbol}; one owner per position."
    cap = trade_cap(prefs, state.regime)
    if notional > cap + 1e-6:
        return f"₹{notional:,.0f} is over the per-trade cap of ₹{cap:,.0f}{' (halved: market risk-off)' if state.regime == 'risk_off' else ''}."
    # The shared trading limits (paper and live), as Practice and Settings > Safety use them.
    if state.deployed + notional > prefs["max_exposure"] + 1e-6:
        return (f"₹{notional:,.0f} more would exceed the max invested of ₹{prefs['max_exposure']:,.0f} "
                f"(₹{state.deployed:,.0f} deployed).")
    limit = prefs["max_trades_per_day"]
    if limit and state.entries_today >= limit:  # 0 is off, as on Settings > Safety
        return f"Already {state.entries_today} trades today (limit {limit})."
    if order.source in AUTO_SOURCES:
        cost = round_trip_cost(price, order.quantity, order.product)
        if cost > MAX_COST_SHARE * notional:
            return (f"Round-trip charges and slippage (₹{cost:,.0f}) are over {MAX_COST_SHARE:.0%} of a "
                    f"₹{notional:,.0f} buy: too small a trade.")
    # An entry that says what it expects (a pick's median, an engine idea's target) must expect to pay
    # for itself: on a ₹3,000 lot the fixed DP charge alone is ~0.5% of a sell (2026-10-23 scan).
    expected = (getattr(order, "context", None) or {}).get("expected_return")
    if expected is not None:
        cost = round_trip_cost(price, order.quantity, order.product)
        if expected * notional < COST_MULTIPLE * cost:
            return (f"Expected gain ₹{expected * notional:,.0f} is under {COST_MULTIPLE:g}x the round-trip charges "
                    f"and slippage (₹{cost:,.0f}): too small to pay for itself.")
    return None
