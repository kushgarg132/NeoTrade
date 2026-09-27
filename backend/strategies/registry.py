"""Factory for the default strategy set, so callers -- the engine runner,
/trading/start -- don't hardcode strategy construction.
"""

from typing import Optional

from backend.components.quant.indian_stocks import ALL_SCAN_STOCKS
from backend.engine.protocols import Strategy
from backend.strategies.intraday.orb_breakout import ORBStrategy
from backend.strategies.intraday.rsi_momentum_scalp import RSIMomentumScalpStrategy
from backend.strategies.intraday.volume_surge import VolumeSurgeStrategy
from backend.strategies.intraday.vwap_reversion import VWAPReversionStrategy
from backend.strategies.longterm.analyst_verdict import AnalystVerdictStrategy
from backend.strategies.longterm.breakout import TechnicalBreakoutStrategy
from backend.strategies.longterm.cash_secured_put import CashSecuredPutStrategy
from backend.strategies.longterm.macd_crossover import MACDCrossoverStrategy
from backend.strategies.longterm.mean_reversion import MeanReversionStrategy
from backend.strategies.longterm.quality_momentum import QualityMomentumStrategy


def build_default_strategies(
    universe: Optional[list[str]] = None,
    symbol_for_token: Optional[dict[int, str]] = None,
    quality_universe: Optional[list[str]] = None,
    quality_scores: Optional[dict[str, float]] = None,
    analyst_verdicts: Optional[dict[str, dict]] = None,
) -> list[Strategy]:
    """`universe` defaults to `indian_stocks.ALL_SCAN_STOCKS` (the existing
    NSE mid/small-cap symbol list already used elsewhere in this codebase),
    not `backend.instruments.master` -- that's an async Mongo-backed lookup,
    and this file, like everything under backend/strategies/, must stay
    I/O-free.

    `symbol_for_token` isn't in the plan's factory pseudocode; it exists for
    the same reason `runner.run()` takes one (see its docstring) --
    `Bar.instrument_token` is all a bar carries, and `Strategy.on_bar`
    doesn't get a resolved symbol handed to it, so each strategy needs its
    own copy of that map. Callers that already built one for the runner/feed
    (e.g. `HistoricalFeed.symbol_for_token`) should pass the same dict here;
    without one, strategies simply never resolve a bar to a symbol and stay
    silent, rather than fabricating a fake token mapping.

    `quality_universe`/`quality_scores` (Task 7) are the pre-built output of
    `backend.screening.universe.build_quality_universe` -- building that
    universe requires an async fundamentals fetch, and this factory, like
    everything under backend/strategies/, must stay I/O-free, so it can't
    build them itself. Default `None` means "don't include
    QualityMomentumStrategy"; pass both (the caller, e.g. Task 6's
    /trading/start route, is expected to have already awaited
    build_quality_universe) to add it as a 5th strategy.

    `analyst_verdicts` (Phase 6) is the pre-built output of
    `backend.ai.analyst_verdict.get_cached_verdict` per symbol -- a Redis read, so this
    factory can't do it itself either. Default `None` means "don't include
    AnalystVerdictStrategy"; the caller (backend.suggestions.scan.scan_universe) is expected
    to have already fetched it for the curated symbol list in
    `backend.options.resolver.FO_UNDERLYINGS`.
    """
    universe = list(universe) if universe is not None else list(ALL_SCAN_STOCKS)
    symbol_for_token = symbol_for_token or {}

    strategies: list[Strategy] = [
        TechnicalBreakoutStrategy(universe, symbol_for_token),
        MeanReversionStrategy(universe, symbol_for_token),
        MACDCrossoverStrategy(universe, symbol_for_token),
        VolumeSurgeStrategy(universe, symbol_for_token),
        VWAPReversionStrategy(universe, symbol_for_token),
        ORBStrategy(universe, symbol_for_token),
        RSIMomentumScalpStrategy(universe, symbol_for_token),
        CashSecuredPutStrategy(universe, symbol_for_token),
    ]
    if quality_universe is not None and quality_scores is not None:
        strategies.append(
            QualityMomentumStrategy(quality_universe, symbol_for_token, quality_scores)
        )
    if analyst_verdicts is not None:
        strategies.append(
            AnalystVerdictStrategy(list(analyst_verdicts.keys()), symbol_for_token, analyst_verdicts)
        )
    return strategies
