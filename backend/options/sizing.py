"""Lot-based, collateral-budget sizing for option-flavored Intents. The
equity risk-sizing path in backend/engine/runner.py::size_intents
(RiskRules.calculate_position_size, a stop-distance risk formula) has no
meaning for an option contract sized by margin/collateral instead -- this
is a deliberately separate function the runner dispatches to, rather than
a branch bolted onto that one. See
docs/superpowers/specs/2026-09-11-phase-5b-fno-cash-secured-put-design.md.
"""

import uuid
from dataclasses import dataclass
from typing import Optional

from backend.core.models import Intent, Order
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.options.premiums import PremiumSource
from backend.options.pricing import black_scholes_put, estimate_margin, realized_volatility
from backend.scoring.composite import CompositeScore

DEFAULT_PUT_OTM_PCT = 0.05
# Too close to expiry to be worth opening a new position against.
MIN_DAYS_TO_EXPIRY = 5
MAX_LOTS_PER_TRADE = 2
# Fraction of account_size treated as max collateral budget at full
# conviction (scored.final == 1.0), scaled linearly down like equity
# size_intents' BASE_RISK_PCT. Needs to comfortably clear one lot's
# estimate_margin (strike * lot_size * MARGIN_APPROXIMATION_PCT) for a
# typical large-cap strike against the ~1M default account_size
# (backend/prefs.py DEFAULTS) -- verified against tests/test_options_sizing.py.
COLLATERAL_BUDGET_PCT = 0.20

_BARS_NEEDED_FOR_VOL = 20


@dataclass(frozen=True)
class OptionSizingResult:
    order: Order
    contract: Instrument
    premium_estimate: float
    margin_estimate: float
    underlying_spot: float
    # True when premium_estimate is the contract's live last traded price
    # from the user's broker; False when it is the Black-Scholes fallback.
    premium_is_live: bool = False


async def size_option_intent(
    intent: Intent,
    scored: CompositeScore,
    ctx,
    account_size: float,
    master: Optional[InstrumentMaster],
    premium_source: Optional[PremiumSource] = None,
) -> Optional[OptionSizingResult]:
    """None means no order: no instrument master given, not enough price
    history, no listed contract far enough from expiry (the broker's NFO
    dump has not been synced -- connect Kite), or the collateral budget
    doesn't cover even one lot.

    The contract is a real listed one: the soonest expiry at least
    MIN_DAYS_TO_EXPIRY out, at the listed strike nearest the target. Its
    premium is the live price from `premium_source` when one is given and
    can price it; otherwise the Black-Scholes estimate, flagged as such."""
    if master is None:
        return None

    history = ctx.history(intent.symbol, _BARS_NEEDED_FOR_VOL)
    if len(history) < _BARS_NEEDED_FOR_VOL:
        return None
    closes = [bar.close for bar in history]
    spot = closes[-1]

    today = ctx.now().date()
    listed = [
        c for c in await master.option_contracts(intent.symbol, "PE")
        if (c.expiry.date() - today).days >= MIN_DAYS_TO_EXPIRY
    ]
    if not listed:
        return None
    expiry = listed[0].expiry.date()
    target = spot * (1 - DEFAULT_PUT_OTM_PCT)
    contract = min((c for c in listed if c.expiry.date() == expiry), key=lambda c: abs(c.strike - target))
    strike = contract.strike

    live = await premium_source(contract) if premium_source is not None else None
    premium = live if live is not None else black_scholes_put(
        spot, strike, (expiry - today).days, realized_volatility(closes),
    )
    margin = estimate_margin(spot, strike, premium, contract.lot_size)

    budget = account_size * (COLLATERAL_BUDGET_PCT * scored.final)
    lots = min(int(budget // max(margin, 1.0)), MAX_LOTS_PER_TRADE)
    if lots < 1:
        return None

    order = Order(
        id=str(uuid.uuid4()), symbol=contract.tradingsymbol, side=intent.side,
        quantity=float(lots * contract.lot_size), order_type="MARKET", limit_price=None,
        product="NRML",
    )
    return OptionSizingResult(
        order=order, contract=contract, premium_estimate=premium,
        margin_estimate=margin * lots, underlying_spot=spot, premium_is_live=live is not None,
    )
