"""Factory for the default strategy set, so callers -- the engine runner,
/trading/start -- don't hardcode strategy construction.
"""

import logging
from typing import Callable, Optional

from backend.components.quant.indian_stocks import ALL_SCAN_STOCKS
from backend.engine.protocols import Strategy
from backend.strategies.built import BlockStrategy, active, load_ok
from backend.strategies.intraday.gap_and_go import GapAndGoStrategy
from backend.strategies.intraday.gap_fill_fade import GapFillFadeStrategy
from backend.strategies.intraday.orb_breakout import ORBStrategy
from backend.strategies.intraday.orb_options import ORBOptionsStrategy
from backend.strategies.intraday.relative_strength_sector import RelativeStrengthSectorStrategy
from backend.strategies.intraday.rsi_momentum_scalp import RSIMomentumScalpStrategy
from backend.strategies.intraday.trend_day_pullback import TrendDayPullbackStrategy
from backend.strategies.intraday.volume_surge import VolumeSurgeStrategy
from backend.strategies.intraday.vwap_reversion import VWAPReversionStrategy
from backend.strategies.longterm.analyst_verdict import AnalystVerdictStrategy
from backend.strategies.longterm.breakout import TechnicalBreakoutStrategy
from backend.strategies.longterm.cash_secured_put import CashSecuredPutStrategy
from backend.strategies.longterm.macd_crossover import MACDCrossoverStrategy
from backend.strategies.longterm.mean_reversion import MeanReversionStrategy
from backend.strategies.longterm.quality_momentum import QualityMomentumStrategy

logger = logging.getLogger(__name__)


def build_default_strategies(
    universe: Optional[list[str]] = None,
    symbol_for_token: Optional[dict[int, str]] = None,
    quality_universe: Optional[list[str]] = None,
    quality_scores: Optional[dict[str, float]] = None,
    analyst_verdicts: Optional[dict[str, dict]] = None,
    option_universe: Optional[list[str]] = None,
    params: Optional[dict[str, dict]] = None,
    catalysts: Optional[dict[str, dict[str, float]]] = None,
    sector_of: Optional[dict[str, str]] = None,
    prev_closes: Optional[dict[str, dict[str, float]]] = None,
    regime_of: Optional[Callable] = None,
    user_id: Optional[str] = None,
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

    `option_universe` adds ORBOptionsStrategy over those symbols. It is kept
    apart from `universe` so the F&O large-caps it needs don't also join
    every equity strategy's universe. Default `None` leaves it out, as
    backtests and the suggestion scan do: it needs live premiums to trade.

    `user_id` adds that user's own built strategies to the global ones; without it only global load.
    """
    universe = list(universe) if universe is not None else list(ALL_SCAN_STOCKS)
    symbol_for_token = symbol_for_token or {}
    # `params` is each strategy's last accepted re-tune, by strategy name
    # (backend/learning/retune.py); missing names keep their defaults.
    params = params or {}

    strategies: list[Strategy] = [
        TechnicalBreakoutStrategy(universe, symbol_for_token, params.get("technical_breakout")),
        MeanReversionStrategy(universe, symbol_for_token, params.get("mean_reversion")),
        MACDCrossoverStrategy(universe, symbol_for_token, params.get("macd_crossover")),
        VolumeSurgeStrategy(universe, symbol_for_token, params.get("volume_surge")),
        VWAPReversionStrategy(universe, symbol_for_token, params.get("vwap_reversion")),
        ORBStrategy(universe, symbol_for_token, params.get("orb_breakout")),
        RSIMomentumScalpStrategy(universe, symbol_for_token, params.get("rsi_momentum_scalp")),
        CashSecuredPutStrategy(universe, symbol_for_token),
        # News-aware intraday strategies (Phase 15.1). `catalysts` is
        # backend/datalayer/catalysts.py's per-day map and `sector_of` the
        # Nifty 200 sector of each symbol; `prev_closes` the previous close per
        # day for feeds that carry only today's bars. Without them gap_and_go and
        # relative_strength_sector stay silent and gap_fill_fade treats
        # every gap as un-catalysed.
        GapAndGoStrategy(universe, symbol_for_token, params.get("gap_and_go"), catalysts=catalysts,
                         prev_closes=prev_closes),
        GapFillFadeStrategy(universe, symbol_for_token, params.get("gap_fill_fade"), catalysts=catalysts,
                            prev_closes=prev_closes),
        TrendDayPullbackStrategy(universe, symbol_for_token, params.get("trend_day_pullback")),
        RelativeStrengthSectorStrategy(universe, symbol_for_token, params.get("relative_strength_sector"),
                                       sector_of=sector_of),
    ]
    if quality_universe is not None and quality_scores is not None:
        strategies.append(
            QualityMomentumStrategy(quality_universe, symbol_for_token, quality_scores)
        )
    if option_universe:
        strategies.append(ORBOptionsStrategy(option_universe, symbol_for_token))
    if analyst_verdicts is not None:
        strategies.append(
            AnalystVerdictStrategy(list(analyst_verdicts.keys()), symbol_for_token, analyst_verdicts)
        )
    for d in active():
        if d.get("owner_id") not in (None, user_id):  # the AI's are global; a user's load only for them
            continue
        if not load_ok(d["spec"]):
            logger.warning("skipping built strategy %s: its spec no longer validates", d["slug"])
            continue
        try:  # load_ok checks keys, not value types; a bad value must not break every caller
            strategies.append(BlockStrategy(
                d["slug"], d["spec"], universe, symbol_for_token, params.get(f"built:{d['slug']}") or d.get("params"),
                regime_of=regime_of, sector_of=sector_of, thesis=d.get("thesis") or "AI-built strategy.",
                prev_closes=prev_closes))
        except Exception:
            logger.warning("skipping built strategy %s: it failed to build", d["slug"], exc_info=True)
    return strategies
