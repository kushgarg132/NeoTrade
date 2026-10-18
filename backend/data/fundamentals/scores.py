"""Pure scoring functions over a FundamentalSnapshot -- no I/O, no network,
just arithmetic over already-fetched data. See the Task 7 report for the
exact weighting rationale.
"""

from backend.data.fundamentals.protocols import FundamentalSnapshot

_DEBT_TO_EQUITY_THRESHOLD = 2.0
# PE <= 10 (earnings_yield >= 10%) is treated as "maximally cheap" for the
# cheapness component below -- a defensible cap for Indian large/mid-caps,
# not a claim that a 40% earnings yield is 4x as good as a 10% one.
_EARNINGS_YIELD_CAP = 0.10


def piotroski_lite_score(snapshot: FundamentalSnapshot) -> int:
    """A reduced Piotroski-style score, 0-5 (NOT the textbook 0-9 score --
    the real Piotroski F-score needs year-over-year balance-sheet deltas
    (change in leverage, change in current ratio, change in shares
    outstanding, etc.) that a single yfinance `.info` snapshot doesn't carry).
    This is a same-day-snapshot proxy over the 5 criteria `FundamentalSnapshot`
    can actually support:
      +1 ROE > 0
      +1 ROA > 0
      +1 revenue_growth > 0
      +1 debt_to_equity < 2.0 (only awarded if debt_to_equity is known)
      +1 earnings_yield > 0
    Missing data for a criterion scores 0 for that criterion (conservative --
    "unknown" never counts as "pass"). Never raises.
    """
    score = 0
    if snapshot.return_on_equity is not None and snapshot.return_on_equity > 0:
        score += 1
    if snapshot.return_on_assets is not None and snapshot.return_on_assets > 0:
        score += 1
    if snapshot.revenue_growth is not None and snapshot.revenue_growth > 0:
        score += 1
    if snapshot.debt_to_equity is not None and snapshot.debt_to_equity < _DEBT_TO_EQUITY_THRESHOLD:
        score += 1
    if snapshot.earnings_yield is not None and snapshot.earnings_yield > 0:
        score += 1
    return score


def quality_score(snapshot: FundamentalSnapshot) -> float:
    """0..1 normalized score for use directly as Intent.strength. Weighting:

        quality_score = 0.7 * (piotroski_lite_score / 5)   [quality]
                       + 0.3 * clamp(earnings_yield / 0.10, 0, 1)   [cheapness]

    70/30 quality-over-cheapness because this screen's job is to build a
    *quality* universe (the momentum strategy layered on top already handles
    entry timing) -- cheapness is a tiebreaker, not the primary filter. Both
    terms are already bounded to [0, 1], so the weighted sum is too. A
    missing earnings_yield contributes 0 to the cheapness term (same
    conservative "unknown never counts as a pass" rule as the Piotroski
    criteria above), never raises.
    """
    quality = piotroski_lite_score(snapshot) / 5
    if snapshot.earnings_yield is None:
        cheapness = 0.0
    else:
        cheapness = max(0.0, min(1.0, snapshot.earnings_yield / _EARNINGS_YIELD_CAP))
    return 0.7 * quality + 0.3 * cheapness
