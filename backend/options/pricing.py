"""Black-Scholes premium estimate (using the underlying's own realized
volatility as an IV proxy, not a live option-chain quote -- no broker
account exists to query one) and a flat margin approximation. Both are
model estimates shown to a human on a LONGTERM suggestion card, never
inputs to auto-execution. See
docs/superpowers/specs/2026-09-11-phase-5b-fno-cash-secured-put-design.md.
"""

import math
from statistics import NormalDist

_NORMAL = NormalDist()


def realized_volatility(closes: list[float], window: int = 20) -> float:
    """Annualized stdev of daily log returns over the trailing `window`
    closes (or fewer if not that many are available), as an IV proxy.
    0.0 if fewer than 2 closes are available."""
    recent = closes[-(window + 1):]
    if len(recent) < 2:
        return 0.0
    log_returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent))]
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / len(log_returns)
    return (variance ** 0.5) * (252 ** 0.5)


def black_scholes_put(
    spot: float, strike: float, days_to_expiry: float, iv: float, risk_free_rate: float = 0.07,
) -> float:
    """Standard Black-Scholes European put premium. Returns 0.0 for a
    non-positive time-to-expiry, volatility, spot, or strike (degenerate
    inputs, guarded rather than raising -- a caller with a stale/zero spot
    should get "no viable premium", not a crash)."""
    if days_to_expiry <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    t = days_to_expiry / 365.0
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * iv ** 2) * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    put = strike * math.exp(-risk_free_rate * t) * _NORMAL.cdf(-d2) - spot * _NORMAL.cdf(-d1)
    return max(put, 0.0)


def black_scholes_call(
    spot: float, strike: float, days_to_expiry: float, iv: float, risk_free_rate: float = 0.07,
) -> float:
    """The call, by put-call parity from black_scholes_put (same guards)."""
    if days_to_expiry <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    t = days_to_expiry / 365.0
    put = black_scholes_put(spot, strike, days_to_expiry, iv, risk_free_rate)
    return max(put + spot - strike * math.exp(-risk_free_rate * t), 0.0)


# ponytail: flat approximation, no live broker margin-API call this phase.
# Upgrade path: an adapter-specific order-margin endpoint (e.g. Kite's
# basket_order_margins) once a live account exists to verify one against --
# see the plan's Global Constraints and the spec's non-goals.
MARGIN_APPROXIMATION_PCT = 0.15


def estimate_margin(spot: float, strike: float, premium: float, lot_size: int) -> float:
    """Flat percentage of contract notional (strike * lot_size) -- a
    conservative SPAN+exposure ballpark, not a real broker margin figure.
    `spot`/`premium` are accepted for interface stability (a future
    per-broker margin call will need them) but unused by this
    approximation."""
    notional = strike * lot_size
    return notional * MARGIN_APPROXIMATION_PCT
