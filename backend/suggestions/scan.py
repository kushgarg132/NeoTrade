"""Scan a universe for fresh long-term suggestions, on demand or on a timer.

A live run only sees bars from the moment it starts, so a strategy needing
50 days of warmup says nothing for 50 sessions. The scan instead replays
history through the same engine, then records only what the newest session
produced -- a breakout from six weeks ago is not a trade anyone can still
take.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.learning.retune import current_params
from backend.learning.adapt import load_rules
from backend.ai.analyst_verdict import get_cached_verdict
from backend.core.clock import SimClock
from backend.core.models import Bar
from backend.data.feeds.historical import HistoricalFeed
from backend.data.providers.store import StoreFundamentals, StoreHistoryProvider
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.engine.persistence import LedgerStore
from backend.engine.portfolio import Portfolio
from backend.engine.runner import run
from backend.instruments.master import InstrumentMaster
from backend.auth.broker_credentials import BrokerCredentialStore, fernet_from_settings
from backend.options.premiums import live_premium_source
from backend.screening.universe import build_quality_universe
from backend.strategies.registry import build_default_strategies
from backend.suggestions.sink import SuggestionSink
from backend.suggestions.store import SuggestionStore

logger = logging.getLogger(__name__)

# Long enough to satisfy the slowest long-term strategy's warmup (50 daily
# bars) with room for holidays and gaps.
LOOKBACK = timedelta(days=400)


class _ArmOnFinalSession:
    """Replays `bars`, arming the sink once it reaches the newest session.

    The bars are materialised first because "the newest session" is only
    knowable after the whole history is in hand.
    """

    def __init__(self, bars: list[Bar], sink: SuggestionSink) -> None:
        self._bars = bars
        self._sink = sink
        self._final_session = max((bar.timestamp for bar in bars), default=None)

    async def __aiter__(self):
        for bar in self._bars:
            self._sink.armed = (
                self._final_session is not None
                and bar.timestamp.date() == self._final_session.date()
            )
            yield bar


class _ArmedOnlyRedis:
    """Suppresses sentiment lookups for every bar except the armed one.

    `get_cached_sentiment` reads whatever is cached *right now*; applying
    that reading to a signal a strategy fired on one of the ~400 warmup
    days would misattribute today's sentiment to a stale day, and multiplies
    into one Redis round trip per warmup-day intent across the whole
    universe -- discarded moments later by the sink regardless of what it
    returns. Only the final (armed) session's intents are current enough
    for the cached value to mean anything.
    """

    def __init__(self, redis, sink: SuggestionSink) -> None:
        self._redis = redis
        self._sink = sink

    async def get(self, key):
        if self._redis is None or not self._sink.armed:
            return None
        return await self._redis.get(key)


async def scan_universe(
    db,
    user_id: str,
    universe: list[str],
    account_size: float = 1_000_000.0,
    max_exposure: float = 1_000_000.0,
    source: str = "scan",
    redis=None,
    now: Optional[datetime] = None,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    master = InstrumentMaster(db)

    instruments = []
    for symbol in universe:
        instrument = await master.get("NSE", symbol)
        if instrument is not None:
            instruments.append(instrument)
    if not instruments:
        logger.info("scan for %s resolved no instruments from %d symbols", user_id, len(universe))
        return []

    symbol_for_token = {i.instrument_token: i.tradingsymbol for i in instruments}

    # The ingest worker keeps a verdict for every followed name
    # (backend/datalayer/news.py), so each scanned symbol may have one.
    analyst_verdicts = {}
    if redis is not None:
        for symbol in symbol_for_token.values():
            verdict = await get_cached_verdict(symbol, redis)
            if verdict is not None:
                analyst_verdicts[symbol] = verdict

    quality_scores = await build_quality_universe(instruments, StoreFundamentals(db))

    if instruments and not quality_scores:
        logger.debug(
            "build_quality_universe returned no scores for %d instrument(s) -- "
            "quality_momentum strategy will be a no-op this scan", len(instruments),
        )
    if not analyst_verdicts:
        logger.debug(
            "no cached analyst verdicts available -- analyst_verdict strategy will be a "
            "no-op this scan"
        )

    strategies = [
        s for s in build_default_strategies(
            universe=[i.tradingsymbol for i in instruments], symbol_for_token=symbol_for_token,
            quality_universe=list(quality_scores) if quality_scores else None,
            quality_scores=quality_scores or None,
            analyst_verdicts=analyst_verdicts or None,
            params=await current_params(db),
        )
        if s.spec.mode == "LONGTERM"
    ]

    feed = HistoricalFeed(
        StoreHistoryProvider(db), instruments, start=now - LOOKBACK, end=now, timeframe="1d", now=now,
    )
    bars = [bar async for bar in feed]
    if not bars:
        return []

    store = SuggestionStore(db)
    held: dict[str, float] = {}
    for trade in await LedgerStore(db, user_id=user_id).get_trades(status="OPEN", venue="paper", mode="LONGTERM"):
        if trade["side"] == "BUY":
            held[trade["symbol"]] = held.get(trade["symbol"], 0.0) + trade["quantity"]
    sink = SuggestionSink(store, user_id=user_id, source=source, held=held)
    sink.armed = False

    before = {s["id"] for s in await store.list(user_id, status="PENDING", limit=1000)}

    await run(
        strategies=strategies,
        feed=_ArmOnFinalSession(bars, sink),
        execution=SimulatedExecutionClient(),
        portfolio=Portfolio(),
        clock=SimClock(bars[0].timestamp),
        symbol_for_token=symbol_for_token,
        redis=_ArmedOnlyRedis(redis, sink),
        account_size=account_size,
        max_exposure=max_exposure,
        ledger=None,
        order_sink=sink,
        master=master,
        # Option proposals carry the contract's live premium when the user
        # has Kite or Upstox connected; otherwise an estimate, flagged.
        premium_source=await live_premium_source(
            db, user_id, BrokerCredentialStore(db, fernet_from_settings()), redis,
        ),
        learned=await load_rules(db, user_id),
    )

    created = [
        s for s in await store.list(user_id, status="PENDING", limit=1000)
        if s["id"] not in before
    ]
    logger.info("scan for %s produced %d suggestion(s)", user_id, len(created))
    return created
