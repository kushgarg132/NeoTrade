"""Builds the quality-screened universe the long-term strategy trades. Does
real I/O (one fundamentals fetch per instrument) -- this lives outside
backend/strategies/ on purpose (see that package's no-I/O rule) and is meant
to be called once by whatever wires up a run (e.g. Task 6's /trading/start
route), with the result passed into QualityMomentumStrategy/registry.py as
plain data.
"""

import asyncio

from backend.instruments.models import Instrument
from backend.data.fundamentals.scores import quality_score
from backend.data.fundamentals.protocols import FundamentalsProvider

_MAX_CONCURRENT_FETCHES = 10


async def build_quality_universe(
    instruments: list[Instrument],
    provider: FundamentalsProvider,
    min_quality_score: float = 0.5,
) -> dict[str, float]:
    """Fetches a snapshot per instrument concurrently (capped by a semaphore
    so this doesn't fire 80+ simultaneous yfinance requests), scores each,
    and returns a symbol -> quality_score mapping for tradingsymbols meeting
    `min_quality_score`. An instrument whose snapshot fetch fails or returns
    None is excluded outright -- never defaulted to a passing (or any) score.
    """
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)

    async def _fetch(instrument: Instrument) -> tuple[str, float] | None:
        async with semaphore:
            try:
                snapshot = await provider.snapshot(instrument)
            except Exception:
                return None
        if snapshot is None:
            return None
        return instrument.tradingsymbol, quality_score(snapshot)

    results = await asyncio.gather(*(_fetch(instrument) for instrument in instruments))
    return {
        symbol: score for symbol, score in (r for r in results if r is not None)
        if score >= min_quality_score
    }
